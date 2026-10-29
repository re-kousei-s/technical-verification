import 'package:flutter/material.dart';

import '../api.dart';
import '../settings_store.dart';

/// 最初の画面：サーバーの URL と、フロア・端末の名前を入れて、登録する。
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key, required this.store, required this.onRegistered});
  final SettingsStore store;
  final void Function(String cameraId) onRegistered;

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

class _SetupScreenState extends State<SetupScreen> {
  late final _server = TextEditingController(text: widget.store.server);
  final _floor = TextEditingController(text: '1');
  final _name = TextEditingController();
  final _existing = TextEditingController();
  bool _busy = false;
  String? _error;

  Future<void> _run(Future<String> Function(Api api) job) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final base = _server.text.trim().replaceAll(RegExp(r'/+$'), '');
    final api = Api(base);
    try {
      final id = await job(api);
      await widget.store.setServer(base);
      await widget.store.setCameraId(id);
      widget.onRegistered(id);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      api.close();
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _register() => _run((api) async {
        final floor = int.tryParse(_floor.text.trim());
        if (floor == null) throw ApiError('フロアは、整数で入れてください');
        final cam = await api.register(floor, _name.text.trim());
        return cam['id'] as String;
      });

  /// すでに登録した端末の ID を入れて、つなぎ直す。
  Future<void> _useExisting() => _run((api) async {
        final id = _existing.text.trim();
        if (id.isEmpty) throw ApiError('端末 ID を入れてください');
        if (await api.camera(id) == null) throw ApiError('サーバーに、その端末が登録されていません');
        return id;
      });

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('端末の登録')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
            controller: _server,
            keyboardType: TextInputType.url,
            decoration: const InputDecoration(labelText: 'サーバーの URL', helperText: '例: https://192.168.2.117:8000（自己署名の証明書でも、つなげます）'),
          ),
          const SizedBox(height: 16),
          Row(children: [
            SizedBox(
              width: 100,
              child: TextField(controller: _floor, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'フロア（階）')),
            ),
            const SizedBox(width: 12),
            Expanded(child: TextField(controller: _name, decoration: const InputDecoration(labelText: '端末の名前（任意）'))),
          ]),
          const SizedBox(height: 16),
          FilledButton(onPressed: _busy ? null : _register, child: Text(_busy ? '通信中…' : '登録する')),
          const Divider(height: 40),
          TextField(controller: _existing, decoration: const InputDecoration(labelText: '登録済みの端末 ID（つなぎ直すとき）', hintText: 'F2-789E')),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _busy ? null : _useExisting, child: const Text('この端末 ID を使う')),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 16), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        ],
      ),
    );
  }
}
