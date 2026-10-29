import 'dart:async';

import 'package:flutter/services.dart';

/// Android のネイティブ側（Kotlin の前面サービス）との橋渡し。
///
/// 映像の送信・サーバーとの接続は、すべて Kotlin の前面サービスが行う。
/// そのため、画面ロック中や、このアプリの画面を閉じたあとも、送信が続く。Dart 側は、操作と表示だけ。
class StreamChannel {
  static const _method = MethodChannel('hdt/stream');
  static const _events = EventChannel('hdt/events');

  /// サービスを開始する（前面サービスとして、通知を出して動く）。
  static Future<void> start({required String baseUrl, required String cameraId, bool insecure = true}) =>
      _method.invokeMethod('start', {'url': baseUrl, 'id': cameraId, 'insecure': insecure});

  static Future<void> stop() => _method.invokeMethod('stop');

  static Future<bool> isRunning() async => (await _method.invokeMethod<bool>('isRunning')) ?? false;

  /// 画面が見えているか。見えている間だけ、狙いを定めるための小さな画像を、サービスが送ってくる。
  static Future<void> setUiVisible(bool visible) => _method.invokeMethod('setUiVisible', visible);

  /// 電池の最適化の対象から外れているか（外れていないと、画面ロック中に止められることがある）。
  static Future<bool> isIgnoringBatteryOptimizations() async =>
      (await _method.invokeMethod<bool>('isIgnoringBatteryOptimizations')) ?? false;

  static Future<void> requestIgnoreBatteryOptimizations() => _method.invokeMethod('requestIgnoreBatteryOptimizations');

  /// サービスからの知らせ。{type: status|thumb|lines, ...}
  static Stream<Map<dynamic, dynamic>> get events =>
      _events.receiveBroadcastStream().map((e) => Map<dynamic, dynamic>.from(e as Map));
}

/// サービスの状態（画面に出す）。
class StreamStatus {
  const StreamStatus({
    this.running = false,
    this.connected = false,
    this.recognize = false,
    this.sendFps = 0,
    this.preview = false,
    this.width = 0,
    this.height = 0,
    this.kbps = 0,
    this.sent = 0,
    this.dropped = 0,
    this.message = '',
  });

  final bool running; // サービスが動いているか
  final bool connected; // サーバーとつながっているか
  final bool recognize; // 認識中か（管理画面の指示）
  final double sendFps; // いま送っている fps（0 なら、送っていない）
  final bool preview; // 見られているか
  final int width, height; // 送っている映像の大きさ
  final int kbps;
  final int sent, dropped;
  final String message; // エラーなど

  factory StreamStatus.fromMap(Map m) => StreamStatus(
        running: m['running'] == true,
        connected: m['connected'] == true,
        recognize: m['recognize'] == true,
        sendFps: (m['sendFps'] as num?)?.toDouble() ?? 0,
        preview: m['preview'] == true,
        width: (m['width'] as num?)?.toInt() ?? 0,
        height: (m['height'] as num?)?.toInt() ?? 0,
        kbps: (m['kbps'] as num?)?.toInt() ?? 0,
        sent: (m['sent'] as num?)?.toInt() ?? 0,
        dropped: (m['dropped'] as num?)?.toInt() ?? 0,
        message: (m['message'] as String?) ?? '',
      );

  String get label {
    if (!running) return '停止中';
    if (!connected) return 'サーバーに接続中…';
    if (sendFps > 0) return '${recognize ? '認識中' : 'プレビュー配信中'} ${sendFps.toStringAsFixed(0)}fps';
    return recognize ? '認識の開始待ち' : '待機中';
  }
}
