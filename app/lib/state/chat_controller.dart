import 'package:flutter/foundation.dart';

import '../models/chat_message.dart';
import '../services/api_client.dart';
import '../services/chat_service.dart';

class ChatController extends ChangeNotifier {
  ChatController({required this.chatService, required this.apiClient});

  final ChatService chatService;
  final ApiClient apiClient;

  final List<ChatBubble> bubbles = [];
  String? sessionId;
  bool streaming = false;

  Future<void> send(String text) async {
    final trimmed = text.trim();
    if (trimmed.isEmpty || streaming) return;
    bubbles.add(ChatBubble(kind: BubbleKind.user, content: trimmed));
    final assistant = ChatBubble(kind: BubbleKind.assistant);
    bubbles.add(assistant);
    streaming = true;
    notifyListeners();
    try {
      await for (final ev in chatService.stream(trimmed, sessionId)) {
        switch (ev) {
          case SessionEvent(:final sessionId):
            this.sessionId = sessionId;
          case TokenEvent(:final content):
            assistant.content += content;
            notifyListeners();
          case ToolEvent(:final name, :final arguments, :final result):
            bubbles.add(ChatBubble(kind: BubbleKind.tool, name: name, arguments: arguments, result: result));
            notifyListeners();
          case ErrorEvent(:final message):
            bubbles.add(ChatBubble(kind: BubbleKind.error, content: message));
            notifyListeners();
          case DoneEvent():
            break;
        }
      }
    } finally {
      streaming = false;
      notifyListeners();
    }
  }

  Future<void> saveNote(String content) async {
    final trimmed = content.trim();
    if (trimmed.isEmpty) return;
    await apiClient.createNote(trimmed);
  }
}
