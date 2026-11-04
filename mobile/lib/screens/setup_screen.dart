import 'package:flutter/material.dart';

import '../api.dart';
import '../settings_store.dart';

/// 最初の画面：サーバーの URL を入れて、管理画面で追加された端末の一覧から、この端末を選ぶ。
/// 端末の追加は、管理画面だけができる（ここでは、追加できない）。
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, required this.store, required this.onRegistered});
  final SettingsStore store;
  final void Function(String cameraId) onRegistered;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  late final _server = TextEditingController(text: widget.store.server);
  List<Map<String, dynamic>> _devices = [];
  bool _busy = false;
  bool _loaded = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  String get _base => _server.text.trim().replaceAll(RegExp(r'/+$'), '');

  Future<void> _load() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = Api(_base);
    try {
      final floors = await api.floors();
      final devices = <Map<String, dynamic>>[];
      for (final f in floors) {
        for (final d in (f['devices'] as List? ?? [])) {
          final m = Map<String, dynamic>.from(d as Map);
          if (m['source'] == 'db') devices.add({...m, 'floor': f['floor']}); // 固定のテスト用端末（yaml）には、スマホがない
        }
      }
      await widget.store.setServer(_base);
      setState(() {
        _devices = devices;
        _loaded = true;
      });
    } catch (e) {
      setState(() => _error = 'サーバーにつながりません: $e');
    } finally {
      api.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _choose(Map<String, dynamic> d) async {
    await widget.store.setServer(_base);
    await widget.store.setCameraId(d['id'] as String);
    widget.onRegistered(d['id'] as String);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('端末を選ぶ')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _server,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(
              labelText: 'サーバーの URL',
              helperText: '例: https://192.168.2.117:8000（自己署名の証明書でも、つなげます）',
              suffixIcon: IconButton(icon: const Icon(Icons.refresh), tooltip: '一覧を更新', onPressed: _busy ? null : _load),
            ),
            onSubmitted: (_) => _load(),
          ),
          const SizedBox(height: 8),
          Text('端末の追加は、管理画面で行います。管理画面で追加した端末の中から、この端末を選んでください。', style: Theme.of(context).textTheme.bodySmall),
          const SizedBox(height: 16),
          if (_busy) const LinearProgressIndicator(),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          if (_loaded && _devices.isEmpty) const Padding(padding: EdgeInsets.all(16), child: Text('まだ端末がありません。管理画面で、端末を追加してください。')),
          for (final d in _devices)
            Card(
              child: ListTile(
                title: Text('${d['floor']}階  ${(d['name'] ?? '') == '' ? d['id'] : d['name']}'),
                subtitle: Text('${d['id']}${d['connected'] == true ? '（送信中）' : ''}'),
                trailing: FilledButton(onPressed: d['connected'] == true ? null : () => _choose(d), child: const Text('選ぶ')),
              ),
            ),
        ],
      ),
    );
  }
}
