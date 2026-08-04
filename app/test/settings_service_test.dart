import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('未保存过时用默认地址', () async {
    final s = SettingsService();
    await s.load();
    expect(s.serverUrl, 'http://10.0.2.2:8000');
  });

  test('保存后新实例加载仍生效', () async {
    final s = SettingsService();
    await s.load();
    await s.setServerUrl('http://192.168.1.10:8000');

    final t = SettingsService();
    await t.load();
    expect(t.serverUrl, 'http://192.168.1.10:8000');
  });
}
