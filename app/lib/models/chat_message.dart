enum BubbleKind { user, assistant, tool, error }

class ChatBubble {
  ChatBubble({
    required this.kind,
    this.content = '',
    this.name,
    this.arguments,
    this.result,
  });

  final BubbleKind kind;
  String content;
  final String? name;
  final Map<String, dynamic>? arguments;
  final Map<String, dynamic>? result;
}
