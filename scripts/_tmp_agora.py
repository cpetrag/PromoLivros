import sqlite3

connection = sqlite3.connect("data/promo_livros.sqlite")
connection.row_factory = sqlite3.Row
print("SETTINGS")
for row in connection.execute(
    "SELECT key, value FROM board_settings WHERE key IN ('send_start','send_end','send_interval_minutes','sending','group_gap_seconds')"
):
    print(row["key"], row["value"])
print("TODAY")
for row in connection.execute(
    """
    SELECT p.id, p.clock, p.status, b.title,
           (SELECT MIN(s.updated_at) FROM board_sends s WHERE s.post_id = p.id AND s.status = 'sent') AS sent_at
    FROM scheduled_posts p
    JOIN scheduled_books b ON b.post_id = p.id AND b.sort_order = 0
    WHERE p.day = '2026-09-28' AND p.id >= 42
    ORDER BY COALESCE(sent_at, '9999'), p.clock, p.id
    """
):
    print(f"{row['id']} {row['clock']} {row['status']} {row['sent_at'] or '-'} {row['title']}")
