-- Tables written by aegis/kvk_sync.py --apply. Postgres. Create them in YOUR database.
-- Rows are upserted on the unique keys below (PostgREST on_conflict + merge-duplicates).
-- Contains player names/ids: keep the database private.

create table if not exists kingdom_war_kingdom_scores (
  taken_at timestamptz not null,
  activity_id bigint,
  round text,
  phase text,
  phase_ends_at timestamptz,
  server_id int not null,
  temple_score bigint,
  season_wins int,
  top_alliance_tag text,
  top_player_name text,
  top_player_score bigint,
  total bigint,
  scores jsonb,
  alliance_duel bigint, alliance_duel_vip bigint, arena bigint, elixir_scramble bigint,
  world_boss bigint, world_boss_damage bigint, escort_raids bigint, arms_race bigint,
  arena_3v3 bigint, peak_arena bigint,
  primary key (taken_at, server_id)
);

create table if not exists kingdom_war_alliance_scores (
  taken_at timestamptz not null,
  activity_id bigint,
  rank int,
  score bigint,
  server_id int,
  union_id bigint not null,
  alliance_tag text,
  alliance_name text,
  leader_name text,
  primary key (taken_at, union_id)
);

create table if not exists kingdom_war_player_scores (
  taken_at timestamptz not null,
  activity_id bigint,
  rank int,
  score bigint,
  server_id int,
  game_player_id bigint not null,
  name text,
  alliance_tag text,
  union_id bigint,
  power bigint,
  kills bigint,
  castle_level int,
  primary key (taken_at, game_player_id)
);

-- With Supabase, enable row level security and use only the service key from kvk_sync.py.
alter table kingdom_war_kingdom_scores enable row level security;
alter table kingdom_war_alliance_scores enable row level security;
alter table kingdom_war_player_scores enable row level security;
