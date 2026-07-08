import sqlite3
p='db.sqlite3'
print('Connecting to', p)
conn=sqlite3.connect(p)
cur=conn.cursor()
try:
    cur.execute('CREATE TABLE IF NOT EXISTS __write_test (id INTEGER PRIMARY KEY, x TEXT)')
    cur.execute("INSERT INTO __write_test (x) VALUES ('ok')")
    conn.commit()
    cur.execute('SELECT COUNT(*) FROM __write_test')
    print('Rowcount:', cur.fetchone()[0])
    cur.execute('DROP TABLE __write_test')
    conn.commit()
    print('Write test succeeded')
except Exception as e:
    print('ERROR', type(e), e)
    conn.rollback()
finally:
    conn.close()
