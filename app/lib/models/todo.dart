class Todo {
  Todo({
    required this.id,
    required this.title,
    this.status = 'pending',
    this.category,
    this.dueAt,
    this.createdAt,
    this.completedAt,
  });

  final int id;
  final String title;
  final String status;
  final String? category;
  final String? dueAt;
  final String? createdAt;
  final String? completedAt;

  bool get isDone => status == 'done';

  factory Todo.fromJson(Map<String, dynamic> json) => Todo(
        id: json['id'] as int,
        title: json['title'] as String,
        status: (json['status'] as String?) ?? 'pending',
        category: json['category'] as String?,
        dueAt: json['due_at'] as String?,
        createdAt: json['created_at'] as String?,
        completedAt: json['completed_at'] as String?,
      );
}
