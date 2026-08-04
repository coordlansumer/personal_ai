import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_ai_app/main.dart';
import 'package:personal_ai_app/services/api_client.dart';
import 'package:personal_ai_app/services/chat_service.dart';
import 'package:personal_ai_app/services/settings_service.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('App 启动后显示聊天页', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final settings = SettingsService()..serverUrl = 'http://test';
    final api = ApiClient(
      baseUrl: 'http://test',
      client: MockClient((req) async {
        final path = req.url.path;
        final body = path.endsWith('/todos')
            ? '{"todos":[],"count":0}'
            : '{"notes":[],"count":0}';
        return http.Response(body, 200, headers: {'content-type': 'application/json'});
      }),
    );
    final chat = ChatService(baseUrl: 'http://test');
    await tester.pumpWidget(
      PersonalAiApp(settings: settings, apiClient: api, chatService: chat),
    );
    await tester.pump();
    expect(find.text('有什么可以帮你？'), findsOneWidget);
  });
}
