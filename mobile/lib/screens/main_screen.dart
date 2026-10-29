import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';

import '../api.dart';
import '../settings_store.dart';
import '../stream_channel.dart';

/// 運用の画面。映像の送信は、前面サービス（Kotlin）が、管理画面の指示に従って行う。
/// この画面は、状態と、狙いを定めるための小さな画像と、結果（IN/OUT）を出すだけ。画面を閉じても、画面ロックしても、送信は続く。
class MainScreen extends StatefulWidget {
  const MainScreen({super.key, required this.store, required this.cameraId, required this.onUnregistered});
  final SettingsStore store;
  final String cameraId;
  final VoidCallback onUnregistered;

  @override
  State<MainScreen> createState() => _MainScreenState();
}

class _MainScreenState extends State<MainScreen> with WidgetsBindingObserver {
  late final Api _api = Api(widget.store.server);
  StreamStatus _status = const StreamStatus();
  Uint8List? _thumb;
  List<List<Offset>> _lines = [];
  Map<String, dynamic>? _cam; // サーバーの端末情報（累計 IN/OUT・フロアの概算）
  bool _batteryOk = true;
  String? _error;
  StreamSubscription? _sub;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _sub = StreamChannel.events.listen(_onEvent, onError: (_) {});
    _poll = Timer.periodic(const Duration(seconds: 2), (_) => _refresh());
    _boot();
  }

  Future<void> _boot() async {
    await StreamChannel.setUiVisible(true);
    await _refresh();
    await _askPermissions();
    await _startService();
    _batteryOk = await StreamChannel.isIgnoringBatteryOptimizations();
    if (mounted) setState(() {});
  }

  /// カメラと、通知（前面サービスの通知に必要）の許可をもらう。
  Future<void> _askPermissions() async {
    final cam = await Permission.camera.request();
    await Permission.notification.request();
    if (!cam.isGranted && mounted) setState(() => _error = 'カメラの許可がありません。設定アプリで、許可してください。');
  }

  Future<void> _startService() async {
    if (!(await Permission.camera.isGranted)) return;
    await StreamChannel.start(baseUrl: widget.store.server, cameraId: widget.cameraId);
  }

  void _onEvent(Map e) {
    switch (e['type']) {
      case 'status':
        setState(() => _status = StreamStatus.fromMap(e));
      case 'thumb':
        setState(() => _thumb = e['bytes'] as Uint8List?);
      case 'lines':
        setState(() => _lines = _parseLines(e['lines']));
    }
  }

  static List<List<Offset>> _parseLines(dynamic v) {
    final out = <List<Offset>>[];
    if (v is List) {
      for (final l in v) {
        final pts = (l is Map ? l['line'] : null) as List?;
        if (pts != null && pts.length == 2) {
          out.add([for (final p in pts) Offset((p[0] as num).toDouble(), (p[1] as num).toDouble())]);
        }
      }
    }
    return out;
  }

  Future<void> _refresh() async {
    try {
      final cam = await _api.camera(widget.cameraId);
      if (!mounted) return;
      if (cam == null) {
        setState(() => _error = 'サーバーに、この端末の登録がありません。登録し直してください。');
        return;
      }
      setState(() {
        _cam = cam;
        _error = null;
        if (_lines.isEmpty) _lines = _parseLines(cam['lines']);
      });
    } catch (e) {
      if (mounted) setState(() => _error = 'サーバーにつながりません: $e');
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    // 画面が見えている間だけ、狙いを定めるための画像を、サービスから受ける
    StreamChannel.setUiVisible(state == AppLifecycleState.resumed);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    StreamChannel.setUiVisible(false);
    _sub?.cancel();
    _poll?.cancel();
    _api.close();
    super.dispose();
  }

  Future<void> _unregister() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('登録を解除しますか？'),
        content: const Text('これまでの通過の記録は、残ります。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('やめる')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('解除する')),
        ],
      ),
    );
    if (ok != true) return;
    await StreamChannel.stop();
    try {
      await _api.unregister(widget.cameraId);
    } catch (e) {
      setState(() => _error = e.toString());
      return;
    }
    await widget.store.setCameraId(null);
    widget.onUnregistered();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final cam = _cam;
    final name = cam == null ? widget.cameraId : '${cam['floor']}階 ${cam['name'] ?? ''}'.trim();
    return Scaffold(
      appBar: AppBar(
        title: Text(name),
        actions: [IconButton(icon: const Icon(Icons.link_off), tooltip: '登録を解除', onPressed: _unregister)],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          // 狙いを定めるための画像（1fps）と、数える線
          AspectRatio(
            aspectRatio: 4 / 3,
            child: Stack(fit: StackFit.expand, children: [
              Container(color: Colors.black),
              if (_thumb != null) Image.memory(_thumb!, fit: BoxFit.contain, gaplessPlayback: true),
              CustomPaint(painter: _LinePainter(_lines)),
              if (_thumb == null)
                const Center(child: Text('カメラの画像を待っています…', style: TextStyle(color: Colors.white70))),
            ]),
          ),
          const SizedBox(height: 12),
          Wrap(spacing: 8, runSpacing: 8, children: [
            Chip(
              avatar: Icon(Icons.circle, size: 12, color: _status.connected ? Colors.green : Colors.orange),
              label: Text(_status.connected ? 'サーバーに接続中' : 'サーバーに接続していません'),
            ),
            Chip(label: Text(_status.label)),
            if (_status.width > 0) Chip(label: Text('${_status.width}×${_status.height}  ${_status.kbps}kbps')),
          ]),
          const SizedBox(height: 12),
          if (cam != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(mainAxisAlignment: MainAxisAlignment.spaceAround, children: [
                  _Count('IN', '${cam['in'] ?? 0}', Colors.green),
                  _Count('OUT', '${cam['out'] ?? 0}', Colors.red),
                  _Count('このフロア', '約 ${(cam['floor_estimate'] as Map?)?['count'] ?? '–'} 人', cs.primary),
                ]),
              ),
            ),
          if (!_batteryOk)
            Card(
              color: cs.tertiaryContainer,
              child: ListTile(
                leading: const Icon(Icons.battery_alert),
                title: const Text('画面ロック中も動かすために、電池の最適化を外してください'),
                subtitle: const Text('外さないと、機種によっては、画面ロックの途中で止められます'),
                trailing: FilledButton(
                  onPressed: () async {
                    await StreamChannel.requestIgnoreBatteryOptimizations();
                    _batteryOk = await StreamChannel.isIgnoringBatteryOptimizations();
                    if (mounted) setState(() {});
                  },
                  child: const Text('外す'),
                ),
              ),
            ),
          if (_error != null || _status.message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(_error ?? _status.message, style: TextStyle(color: cs.error)),
            ),
          const SizedBox(height: 12),
          Row(children: [
            Expanded(
              child: _status.running
                  ? OutlinedButton.icon(
                      onPressed: () async {
                        await StreamChannel.stop();
                      },
                      icon: const Icon(Icons.stop),
                      label: const Text('サービスを止める'),
                    )
                  : FilledButton.icon(onPressed: _startService, icon: const Icon(Icons.play_arrow), label: const Text('サービスを開始')),
            ),
          ]),
          const SizedBox(height: 8),
          Text(
            '認識の開始・停止、リアルタイム表示、線の編集は、管理画面から行います。\n通知に「人検出クライアント」が出ている間は、画面ロック中も、指示に従って映像を送ります。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}

class _Count extends StatelessWidget {
  const _Count(this.label, this.value, this.color);
  final String label, value;
  final Color color;

  @override
  Widget build(BuildContext context) => Column(children: [
        Text(label, style: Theme.of(context).textTheme.labelMedium),
        Text(value, style: Theme.of(context).textTheme.headlineSmall?.copyWith(color: color, fontWeight: FontWeight.w600)),
      ]);
}

/// 画像の上に、数える線を描く（座標は、画像に対する割合）。
class _LinePainter extends CustomPainter {
  _LinePainter(this.lines);
  final List<List<Offset>> lines;

  static const _colors = [Color(0xffff3b30), Color(0xffffcc00), Color(0xff00c7ff), Color(0xffff7ad9), Color(0xff7dff7a), Color(0xffb388ff)];

  @override
  void paint(Canvas canvas, Size size) {
    // 画像は 4:3 の枠に、contain で出ている。線も、同じ枠に合わせる
    for (var i = 0; i < lines.length; i++) {
      final a = Offset(lines[i][0].dx * size.width, lines[i][0].dy * size.height);
      final b = Offset(lines[i][1].dx * size.width, lines[i][1].dy * size.height);
      final p = Paint()
        ..color = _colors[i % _colors.length]
        ..strokeWidth = 3;
      canvas.drawLine(a, b, p);
      canvas.drawCircle(a, 5, p);
      canvas.drawCircle(b, 5, p);
      // IN の向き（始点→終点の左側）に、矢印を出す
      final d = b - a;
      final len = d.distance == 0 ? 1.0 : d.distance;
      final n = Offset(d.dy / len, -d.dx / len);
      final m = (a + b) / 2;
      canvas.drawLine(m, m + n * 24, Paint()
        ..color = Colors.greenAccent
        ..strokeWidth = 3);
    }
  }

  @override
  bool shouldRepaint(_LinePainter old) => old.lines != lines;
}
