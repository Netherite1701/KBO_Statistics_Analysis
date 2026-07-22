CREATE TABLE crawl_runs (
    crawl_run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'partial')),
    arguments_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at TEXT,
    summary_json TEXT,
    error_text TEXT
);

CREATE TABLE source_requests (
    source_request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_run_id INTEGER REFERENCES crawl_runs(crawl_run_id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    season TEXT,
    game_id TEXT,
    endpoint TEXT NOT NULL,
    method TEXT NOT NULL,
    parameters_json TEXT NOT NULL DEFAULT '{}',
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    status_code INTEGER,
    response_content_type TEXT,
    raw_path TEXT,
    sha256 TEXT,
    response_size_bytes INTEGER,
    compressed_size_bytes INTEGER,
    elapsed_ms INTEGER,
    attempt INTEGER NOT NULL DEFAULT 1 CHECK (attempt > 0),
    state TEXT NOT NULL CHECK (state IN ('succeeded', 'failed')),
    error_text TEXT,
    CHECK (sha256 IS NULL OR length(sha256) = 64),
    CHECK (response_size_bytes IS NULL OR response_size_bytes >= 0),
    CHECK (compressed_size_bytes IS NULL OR compressed_size_bytes >= 0),
    CHECK (elapsed_ms IS NULL OR elapsed_ms >= 0)
);

CREATE TABLE teams (
    team_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    short_name TEXT,
    active_from INTEGER,
    active_to INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE team_aliases (
    source TEXT NOT NULL,
    external_team_id TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    source_name TEXT,
    PRIMARY KEY (source, external_team_id)
);

CREATE TABLE players (
    player_id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    birth_date TEXT,
    position TEXT,
    bats TEXT,
    throws TEXT,
    active_from INTEGER,
    active_to INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE player_external_ids (
    source TEXT NOT NULL,
    external_player_id TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    source_name TEXT,
    PRIMARY KEY (source, external_player_id)
);

CREATE TABLE games (
    game_id TEXT PRIMARY KEY,
    season INTEGER NOT NULL,
    series_type TEXT NOT NULL,
    game_date TEXT NOT NULL,
    scheduled_start TEXT,
    status TEXT NOT NULL,
    ingestion_status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (ingestion_status IN (
            'discovered', 'raw', 'parsed', 'validated', 'quarantined'
        )),
    away_team_id TEXT REFERENCES teams(team_id),
    home_team_id TEXT REFERENCES teams(team_id),
    ballpark TEXT,
    doubleheader_game INTEGER,
    is_cancelled INTEGER NOT NULL DEFAULT 0 CHECK (is_cancelled IN (0, 1)),
    is_suspended INTEGER NOT NULL DEFAULT 0 CHECK (is_suspended IN (0, 1)),
    away_score INTEGER,
    home_score INTEGER,
    source_updated_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (doubleheader_game IS NULL OR doubleheader_game > 0),
    CHECK (away_score IS NULL OR away_score >= 0),
    CHECK (home_score IS NULL OR home_score >= 0)
);

CREATE TABLE game_source_ids (
    source TEXT NOT NULL,
    external_game_id TEXT NOT NULL,
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    PRIMARY KEY (source, external_game_id),
    UNIQUE (source, game_id)
);

CREATE TABLE roster_daily (
    roster_date TEXT NOT NULL,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    roster_status TEXT NOT NULL,
    position TEXT,
    transaction_type TEXT,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    PRIMARY KEY (roster_date, team_id, player_id)
);

CREATE TABLE lineups (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    entry_seq INTEGER NOT NULL CHECK (entry_seq >= 0),
    batting_order INTEGER,
    position TEXT,
    is_starter INTEGER NOT NULL DEFAULT 0 CHECK (is_starter IN (0, 1)),
    entered_inning INTEGER,
    left_inning INTEGER,
    PRIMARY KEY (game_id, team_id, player_id, entry_seq),
    CHECK (batting_order IS NULL OR batting_order BETWEEN 1 AND 9)
);

CREATE TABLE plate_appearances (
    plate_appearance_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    relay_no INTEGER NOT NULL,
    inning INTEGER NOT NULL CHECK (inning > 0),
    half TEXT NOT NULL CHECK (half IN ('top', 'bottom')),
    batting_team_id TEXT REFERENCES teams(team_id),
    batter_id TEXT REFERENCES players(player_id),
    pitcher_id TEXT REFERENCES players(player_id),
    batting_order INTEGER,
    outs_before INTEGER,
    balls_before INTEGER,
    strikes_before INTEGER,
    result_code TEXT,
    result_text TEXT,
    result_event_type INTEGER,
    runs_scored INTEGER NOT NULL DEFAULT 0,
    rbi INTEGER,
    is_complete INTEGER NOT NULL DEFAULT 0 CHECK (is_complete IN (0, 1)),
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    raw_json TEXT,
    UNIQUE (game_id, relay_no),
    CHECK (outs_before IS NULL OR outs_before BETWEEN 0 AND 2),
    CHECK (balls_before IS NULL OR balls_before BETWEEN 0 AND 3),
    CHECK (strikes_before IS NULL OR strikes_before BETWEEN 0 AND 2)
);

CREATE TABLE pitches (
    pitch_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    plate_appearance_id TEXT REFERENCES plate_appearances(plate_appearance_id)
        ON DELETE CASCADE,
    pitcher_id TEXT REFERENCES players(player_id),
    batter_id TEXT REFERENCES players(player_id),
    seqno INTEGER,
    pitch_num INTEGER,
    pitch_result_code TEXT,
    pitch_result_text TEXT,
    balls_after INTEGER,
    strikes_after INTEGER,
    outs_after INTEGER,
    runner_on_first INTEGER,
    runner_on_second INTEGER,
    runner_on_third INTEGER,
    pitch_type TEXT,
    speed_kph REAL,
    batter_stance TEXT,
    x0 REAL,
    y0 REAL,
    z0 REAL,
    vx0 REAL,
    vy0 REAL,
    vz0 REAL,
    ax REAL,
    ay REAL,
    az REAL,
    cross_plate_x REAL,
    cross_plate_y REAL,
    plate_height REAL,
    strike_zone_top REAL,
    strike_zone_bottom REAL,
    ballcount TEXT,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    raw_json TEXT,
    CHECK (balls_after IS NULL OR balls_after BETWEEN 0 AND 4),
    CHECK (strikes_after IS NULL OR strikes_after BETWEEN 0 AND 3),
    CHECK (outs_after IS NULL OR outs_after BETWEEN 0 AND 3),
    CHECK (runner_on_first IS NULL OR runner_on_first IN (0, 1)),
    CHECK (runner_on_second IS NULL OR runner_on_second IN (0, 1)),
    CHECK (runner_on_third IS NULL OR runner_on_third IN (0, 1)),
    UNIQUE (game_id, seqno)
);

CREATE TABLE game_events (
    game_event_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    relay_no INTEGER,
    seqno INTEGER,
    inning INTEGER,
    half TEXT,
    event_type INTEGER,
    event_code TEXT,
    event_text TEXT,
    team_id TEXT REFERENCES teams(team_id),
    player_id TEXT REFERENCES players(player_id),
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    raw_json TEXT,
    UNIQUE (game_id, relay_no, seqno)
);

CREATE TABLE batting_boxscores (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    lineup_seq INTEGER NOT NULL DEFAULT 0,
    plate_appearances INTEGER,
    at_bats INTEGER,
    runs INTEGER,
    hits INTEGER,
    doubles INTEGER,
    triples INTEGER,
    home_runs INTEGER,
    rbi INTEGER,
    walks INTEGER,
    intentional_walks INTEGER,
    hit_by_pitch INTEGER,
    strikeouts INTEGER,
    sacrifice_hits INTEGER,
    sacrifice_flies INTEGER,
    stolen_bases INTEGER,
    caught_stealing INTEGER,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    PRIMARY KEY (game_id, team_id, player_id, lineup_seq)
);

CREATE TABLE pitching_boxscores (
    game_id TEXT NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    team_id TEXT NOT NULL REFERENCES teams(team_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    appearance_seq INTEGER NOT NULL DEFAULT 0,
    outs_recorded INTEGER,
    batters_faced INTEGER,
    pitches INTEGER,
    hits INTEGER,
    home_runs INTEGER,
    walks INTEGER,
    intentional_walks INTEGER,
    hit_by_pitch INTEGER,
    strikeouts INTEGER,
    runs INTEGER,
    earned_runs INTEGER,
    result TEXT,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    PRIMARY KEY (game_id, team_id, player_id, appearance_seq)
);

CREATE TABLE player_daily_official (
    record_date TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    team_id TEXT REFERENCES teams(team_id),
    record_type TEXT NOT NULL,
    is_month_total INTEGER NOT NULL DEFAULT 0 CHECK (is_month_total IN (0, 1)),
    metrics_json TEXT NOT NULL,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    PRIMARY KEY (record_date, player_id, record_type, is_month_total)
);

CREATE TABLE weather (
    game_id TEXT PRIMARY KEY REFERENCES games(game_id) ON DELETE CASCADE,
    observed_at TEXT,
    condition TEXT,
    temperature_c REAL,
    humidity_pct REAL,
    precipitation_probability_pct REAL,
    precipitation_mm REAL,
    wind_speed_mps REAL,
    wind_direction TEXT,
    source_request_id INTEGER REFERENCES source_requests(source_request_id)
);

CREATE TABLE statiz_metrics (
    metric_date TEXT NOT NULL,
    player_id TEXT NOT NULL REFERENCES players(player_id),
    metric_group TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    source_request_id INTEGER REFERENCES source_requests(source_request_id),
    PRIMARY KEY (metric_date, player_id, metric_group)
);

CREATE TABLE data_quality_issues (
    data_quality_issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    crawl_run_id INTEGER REFERENCES crawl_runs(crawl_run_id) ON DELETE SET NULL,
    game_id TEXT REFERENCES games(game_id) ON DELETE CASCADE,
    source TEXT,
    entity_type TEXT NOT NULL DEFAULT 'game',
    entity_id TEXT,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    issue_code TEXT NOT NULL,
    message TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'ignored')),
    detected_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    resolved_at TEXT
);

CREATE INDEX idx_source_requests_run ON source_requests(crawl_run_id);
CREATE INDEX idx_source_requests_game ON source_requests(source, game_id);
CREATE INDEX idx_source_requests_sha256 ON source_requests(sha256);
CREATE INDEX idx_games_season_date ON games(season, game_date);
CREATE INDEX idx_games_ingestion_status ON games(ingestion_status);
CREATE INDEX idx_roster_player_date ON roster_daily(player_id, roster_date);
CREATE INDEX idx_plate_appearances_game_order
    ON plate_appearances(game_id, inning, half, relay_no);
CREATE INDEX idx_plate_appearances_batter
    ON plate_appearances(batter_id, game_id);
CREATE INDEX idx_pitches_game_order ON pitches(game_id, seqno);
CREATE INDEX idx_pitches_plate_appearance ON pitches(plate_appearance_id, pitch_num);
CREATE INDEX idx_pitches_batter ON pitches(batter_id, game_id);
CREATE INDEX idx_pitches_pitcher ON pitches(pitcher_id, game_id);
CREATE INDEX idx_game_events_game_order ON game_events(game_id, relay_no, seqno);
CREATE INDEX idx_quality_game_status ON data_quality_issues(game_id, status);
