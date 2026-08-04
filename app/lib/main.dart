import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'home_shell.dart';
import 'services/api_client.dart';
import 'services/chat_service.dart';
import 'services/settings_service.dart';
import 'state/chat_controller.dart';
import 'state/notes_controller.dart';
import 'state/todos_controller.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final settings = SettingsService();
  await settings.load();
  final apiClient = ApiClient(baseUrl: settings.serverUrl);
  final chatService = ChatService(baseUrl: settings.serverUrl);
  runApp(PersonalAiApp(settings: settings, apiClient: apiClient, chatService: chatService));
}

class PersonalAiApp extends StatelessWidget {
  const PersonalAiApp({
    super.key,
    required this.settings,
    required this.apiClient,
    required this.chatService,
  });

  final SettingsService settings;
  final ApiClient apiClient;
  final ChatService chatService;

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider.value(value: settings),
        Provider.value(value: apiClient),
        Provider.value(value: chatService),
        ChangeNotifierProvider(
          create: (_) => ChatController(chatService: chatService, apiClient: apiClient),
        ),
        ChangeNotifierProvider(create: (_) => TodosController(apiClient: apiClient)..load()),
        ChangeNotifierProvider(create: (_) => NotesController(apiClient: apiClient)..load()),
      ],
      child: MaterialApp(
        title: 'Personal AI',
        theme: ThemeData(colorSchemeSeed: Colors.indigo, useMaterial3: true),
        home: const HomeShell(),
      ),
    );
  }
}
