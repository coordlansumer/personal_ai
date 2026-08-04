import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/main.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('App 启动后显示聊天页', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsService()..serverUrl = 'http://test';
    final api = ApiClient(baseUrl: 'http://test');
    final chat = ChatService(baseUrl: 'http://test');
    await tester.pumpWidget(
      PersonalAiApp(settings: settings, apiClient: api, chatService: chat),
    );
    await tester.pump();
    expect(find.text('有什么可以帮你？'), findsOneWidget);
  });
}
