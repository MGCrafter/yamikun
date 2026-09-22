from db import Database


def test_merged_and_existing_global_levels_follow_total_xp(tmp_path):
    path = str(tmp_path / 'bot.db')
    db = Database(path)
    db.conn.executemany(
        'INSERT INTO levels (guild_id,user_id,xp,level,coins) VALUES (?,42,1000,4,600)',
        [(111,), (222,)],
    )
    db.conn.execute('INSERT INTO levels (guild_id,user_id,xp,level,coins) VALUES (0,43,2000,4,1200)')
    db.conn.commit()
    db.close()
    for _ in range(2):
        db = Database(path)
        for uid in (42, 43):
            row = db.get_user(111, uid)
            assert (row['xp'], row['level'], row['coins']) == (2000, 6, 1200)
        db.close()


def test_card_collisions_preserve_definitions_inventory_and_favorites(tmp_path):
    path = str(tmp_path / 'bot.db')
    db = Database(path)
    for table, inventory in [('custom_cards', 'card_inventory'), ('server_cards', 'server_inventory')]:
        db.conn.executemany(
            f'INSERT INTO {table} (guild_id,card_id,name,rarity) VALUES (?,?,?,?)',
            [(0, 'hero', 'Hero', 'common'), (111, 'hero', 'Hero', 'common'),
             (222, 'hero', 'Hero', 'legendary'),
             (333, 'hero-guild-222', 'Other', 'rare')],
        )
        db.conn.executemany(
            f'INSERT INTO {inventory} (guild_id,user_id,card_id,count) VALUES (?,42,?,?)',
            [(0, 'hero', 1), (111, 'hero', 2), (222, 'hero', 4), (333, 'hero-guild-222', 1)],
        )
    db.conn.execute("INSERT INTO fav_game_cards VALUES (222,42,'game','hero')")
    db.conn.execute("INSERT INTO profiles (guild_id,user_id,fav_card) VALUES (222,42,'hero')")
    db.conn.commit()
    db.close()
    for _ in range(2):
        db = Database(path)
        for table, inventory in [('custom_cards', 'card_inventory'), ('server_cards', 'server_inventory')]:
            rows = db.conn.execute(f'SELECT * FROM {table}').fetchall()
            assert len(rows) == 3
            assert all(r['guild_id'] == 0 for r in rows)
            legendary = next(r['card_id'] for r in rows if r['rarity'] == 'legendary')
            assert legendary == 'hero-guild-222-2'
            owned = {r['card_id']: r['count'] for r in db.conn.execute(f'SELECT * FROM {inventory}')}
            assert owned == {'hero': 3, legendary: 4, 'hero-guild-222': 1}
        assert db.get_fav_game_cards(222, 42) == {'game': legendary}
        assert db.get_fav_card(222, 42) == legendary
        db.close()
