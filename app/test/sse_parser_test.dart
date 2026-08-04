import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_app/services/chat_service.dart';

void main() {
  test('解析 session 事件', () {
    final ev = parseSseLine('data: {"type":"session","session_id":"abc"}');
    expect(ev, isA<SessionEvent>());
    expect((ev as SessionEvent).sessionId, 'abc');
  });

  test('解析 token 事件', () {
    final ev = parseSseLine('data: {"type":"token","content":"你好"}');
    expect(ev, isA<TokenEvent>());
    expect((ev as TokenEvent).content, '你好');
  });

  test('解析 tool 事件', () {
    final ev = parseSseLine(
        'data: {"type":"tool","name":"create_todo","arguments":{"title":"买牛奶"},"result":{"id":1}}');
    expect(ev, isA<ToolEvent>());
    final t = ev as ToolEvent;
    expect(t.name, 'create_todo');
    expect(t.arguments['title'], '买牛奶');
    expect(t.result['id'], 1);
  });

  test('解析 error 与 done', () {
    expect((parseSseLine('data: {"type":"error","message":"炸了"}') as ErrorEvent).message, '炸了');
    expect(parseSseLine('data: {"type":"done"}'), isA<DoneEvent>());
  });

  test('非 data 行 / 非 JSON / 未知类型返回 null', () {
    expect(parseSseLine(''), isNull);
    expect(parseSseLine('data: not-json'), isNull);
    expect(parseSseLine('data: {"type":"weird"}'), isNull);
  });
}
