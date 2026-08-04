import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/chat_message.dart';
import '../state/chat_controller.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final text = _input.text;
    if (text.trim().isEmpty) return;
    _input.clear();
    await context.read<ChatController>().send(text);
  }

  Future<void> _note() async {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    final messenger = ScaffoldMessenger.of(context);
    try {
      await context.read<ChatController>().saveNote(text);
      _input.clear();
      messenger.showSnackBar(const SnackBar(content: Text('已记录到笔记')));
    } catch (_) {
      messenger.showSnackBar(const SnackBar(content: Text('记录失败，请检查服务器地址')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ChatController>();
    final bubbles = controller.bubbles.reversed.toList();
    return Column(
      children: [
        Expanded(
          child: bubbles.isEmpty
              ? const Center(child: Text('有什么可以帮你？', style: TextStyle(color: Colors.grey)))
              : ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.all(12),
                  itemCount: bubbles.length,
                  itemBuilder: (_, i) => _BubbleView(bubble: bubbles[i]),
                ),
        ),
        SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _input,
                    minLines: 1,
                    maxLines: 4,
                    decoration: const InputDecoration(
                      hintText: '输入消息，或记成笔记…',
                      border: OutlineInputBorder(borderRadius: BorderRadius.all(Radius.circular(20))),
                      contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    ),
                    onSubmitted: (_) => _send(),
                  ),
                ),
                IconButton(
                  tooltip: '把当前输入记成笔记',
                  icon: const Icon(Icons.note_add_outlined),
                  onPressed: _note,
                ),
                IconButton.filled(
                  tooltip: '发送',
                  icon: const Icon(Icons.send),
                  onPressed: _send,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _BubbleView extends StatelessWidget {
  const _BubbleView({required this.bubble});

  final ChatBubble bubble;

  @override
  Widget build(BuildContext context) {
    switch (bubble.kind) {
      case BubbleKind.user:
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primary,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content, style: const TextStyle(color: Colors.white)),
          ),
        );
      case BubbleKind.assistant:
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content),
          ),
        );
      case BubbleKind.tool:
        return Container(
          margin: const EdgeInsets.only(bottom: 8),
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: Colors.grey.shade100,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.grey.shade300),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('工具调用: ${bubble.name}',
                  style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 4),
              Text(_pretty(bubble.arguments)),
              if (bubble.result != null && bubble.result!.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(_pretty(bubble.result)),
              ],
            ],
          ),
        );
      case BubbleKind.error:
        return Align(
          alignment: Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.errorContainer,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Text(bubble.content),
          ),
        );
    }
  }

  String _pretty(Map<String, dynamic>? m) {
    if (m == null || m.isEmpty) return '';
    return JsonEncoder.withIndent('  ').convert(m);
  }
}
