import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';

/// サーバー（Go の backend）の、スマホ向け API。
///
/// 検証環境の gateway は、自己署名の証明書なので、証明書の検査を省く（[insecure] が true のとき）。
class Api {
  Api(this.base, {this.insecure = true}) : _client = _makeClient(insecure);

  /// 例: https://192.168.2.117:8000
  final String base;
  final bool insecure;
  final http.Client _client;

  static http.Client _makeClient(bool insecure) {
    final inner = HttpClient()..connectionTimeout = const Duration(seconds: 8);
    if (insecure) inner.badCertificateCallback = (_, _, _) => true;
    return IOClient(inner);
  }

  Uri _u(String path) => Uri.parse('$base$path');

  Future<dynamic> _json(http.Response r) async {
    final body = utf8.decode(r.bodyBytes);
    final data = body.isEmpty ? null : jsonDecode(body);
    if (r.statusCode >= 400) {
      throw ApiError(data is Map ? (data['detail']?.toString() ?? '通信に失敗しました') : '通信に失敗しました（${r.statusCode}）');
    }
    return data;
  }

  /// 管理画面で追加された端末の一覧（フロアごと）。端末の追加は、管理画面だけ。スマホは、この一覧から選ぶ。
  /// 戻り値：[{floor, devices: [{id, name, floor, source, connected, …}]}]
  Future<List<Map<String, dynamic>>> floors() async {
    final r = await _client.get(_u('/api/floors'));
    return [for (final f in (await _json(r)) as List) Map<String, dynamic>.from(f as Map)];
  }

  /// 端末の設定と、累計の IN/OUT・フロアの概算。登録が無ければ null。
  Future<Map<String, dynamic>?> camera(String id) async {
    final r = await _client.get(_u('/api/cameras/${Uri.encodeComponent(id)}'));
    if (r.statusCode == 404) return null;
    return Map<String, dynamic>.from(await _json(r));
  }

  void close() => _client.close();
}

class ApiError implements Exception {
  ApiError(this.message);
  final String message;
  @override
  String toString() => message;
}
