import 'package:flutter/foundation.dart';

import '../models/note.dart';
import '../services/api_client.dart';

class NotesController extends ChangeNotifier {
  NotesController({required this.apiClient});

  final ApiClient apiClient;

  List<Note> notes = [];
  bool loading = false;
  bool searching = false;
  String? error;

  Future<void> load() async {
    loading = true;
    searching = false;
    error = null;
    notifyListeners();
    try {
      notes = await apiClient.listNotes();
    } catch (e) {
      error = '加载失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> search(String query) async {
    final q = query.trim();
    loading = true;
    searching = q.isNotEmpty;
    error = null;
    notifyListeners();
    try {
      notes = q.isEmpty ? await apiClient.listNotes() : await apiClient.searchNotes(q);
    } catch (e) {
      error = '搜索失败: $e';
    } finally {
      loading = false;
      notifyListeners();
    }
  }

  Future<void> remove(Note note) async {
    notes.removeWhere((n) => n.id == note.id);
    notifyListeners();
    var failed = false;
    try {
      await apiClient.deleteNote(note.id);
    } catch (_) {
      failed = true;
    }
    await load();
    if (failed) {
      error = '删除失败';
      notifyListeners();
    }
  }
}
