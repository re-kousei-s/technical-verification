import 'package:flutter/material.dart';

import 'screens/main_screen.dart';
import 'screens/setup_screen.dart';
import 'settings_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = await SettingsStore.load();
  runApp(HdtApp(store: store));
}

class HdtApp extends StatefulWidget {
  const HdtApp({super.key, required this.store});
  final SettingsStore store;

  @override
  State<HdtApp> createState() => _HdtAppState();
}

class _HdtAppState extends State<HdtApp> {
  late String? _cameraId = widget.store.cameraId;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '人検出 クライアント',
      theme: ThemeData(colorSchemeSeed: const Color(0xFF1A73E8), useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: const Color(0xFF1A73E8), useMaterial3: true, brightness: Brightness.dark),
      home: _cameraId == null
          ? SetupScreen(
              store: widget.store,
              onRegistered: (id) => setState(() => _cameraId = id),
            )
          : MainScreen(
              store: widget.store,
              cameraId: _cameraId!,
              onUnregistered: () => setState(() => _cameraId = null),
            ),
    );
  }
}
