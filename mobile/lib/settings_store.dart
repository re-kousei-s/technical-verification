import 'package:shared_preferences/shared_preferences.dart';

/// このアプリに覚えておく設定（サーバーの URL・登録した端末の ID）。
class SettingsStore {
  SettingsStore(this._p);
  final SharedPreferences _p;

  static Future<SettingsStore> load() async => SettingsStore(await SharedPreferences.getInstance());

  String get server => _p.getString('server') ?? 'https://192.168.2.117:8000';
  String? get cameraId => _p.getString('cameraId');

  Future<void> setServer(String v) => _p.setString('server', v);
  Future<void> setCameraId(String? v) => v == null ? _p.remove('cameraId') : _p.setString('cameraId', v);
}
