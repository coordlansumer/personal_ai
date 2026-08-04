class Note {
  Note({required this.id, required this.content, this.createdAt, this.score});

  final int id;
  final String content;
  final String? createdAt;
  final double? score;

  factory Note.fromListJson(Map<String, dynamic> json) => Note(
        id: json['id'] as int,
        content: json['content'] as String,
        createdAt: json['created_at'] as String?,
      );

  factory Note.fromSearchJson(Map<String, dynamic> json) => Note(
        id: int.tryParse((json['note_id'] as String?) ?? '') ?? 0,
        content: (json['content'] as String?) ?? '',
        score: (json['score'] as num?)?.toDouble(),
      );
}
