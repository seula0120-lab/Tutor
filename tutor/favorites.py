"""즐겨찾기: 요약 카드에서 별표를 눌러 저장한 질문. 서버 DB(favorites)에 저장하고, 열면 같은 질문을 다시 검색한다.
같은 질문을 또 저장해도 한 줄만 남는다(범위만 갱신)."""
import time

MAX_QUERY = 200


def clean(query):
    query = (query or "").strip()
    if not query:
        raise ValueError("질문이 비어 있습니다.")
    if len(query) > MAX_QUERY:
        raise ValueError(f"질문은 {MAX_QUERY}자 이하여야 합니다.")
    return query


def add(conn, query, scope="all", now=None):
    query = clean(query)
    now = time.time() if now is None else now
    with conn:
        conn.execute("""INSERT INTO favorites(user_id, query, scope, created_at) VALUES (?,?,?,?)
                        ON CONFLICT(user_id, query) DO UPDATE SET scope = excluded.scope""", (conn.user_id, query, str(scope or "all"), now))
    return list_all(conn)


def remove(conn, query):
    query = clean(query)
    with conn:
        conn.execute("DELETE FROM favorites WHERE user_id = ? AND query = ?", (conn.user_id, query))
    return list_all(conn)


def list_all(conn):
    """최근에 저장한 순."""
    rows = conn.execute("SELECT query, scope, created_at FROM favorites WHERE user_id = ? ORDER BY created_at DESC, id DESC", (conn.user_id,)).fetchall()
    return [{"query": r["query"], "scope": r["scope"], "created_at": r["created_at"]} for r in rows]
