DROP INDEX IF EXISTS idx_pitches_game_order;
DROP INDEX IF EXISTS idx_pitches_plate_appearance;
DROP INDEX IF EXISTS idx_pitches_batter;
DROP INDEX IF EXISTS idx_pitches_pitcher;

ALTER TABLE pitches RENAME TO pitches_v1;

CREATE TABLE pitches (
    pitch_id TEXT NOT NULL,
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
    PRIMARY KEY (game_id, pitch_id),
    CHECK (balls_after IS NULL OR balls_after BETWEEN 0 AND 4),
    CHECK (strikes_after IS NULL OR strikes_after BETWEEN 0 AND 3),
    CHECK (outs_after IS NULL OR outs_after BETWEEN 0 AND 3),
    CHECK (runner_on_first IS NULL OR runner_on_first IN (0, 1)),
    CHECK (runner_on_second IS NULL OR runner_on_second IN (0, 1)),
    CHECK (runner_on_third IS NULL OR runner_on_third IN (0, 1)),
    UNIQUE (game_id, seqno)
);

INSERT INTO pitches (
    pitch_id, game_id, plate_appearance_id, pitcher_id, batter_id,
    seqno, pitch_num, pitch_result_code, pitch_result_text,
    balls_after, strikes_after, outs_after,
    runner_on_first, runner_on_second, runner_on_third,
    pitch_type, speed_kph, batter_stance,
    x0, y0, z0, vx0, vy0, vz0, ax, ay, az,
    cross_plate_x, cross_plate_y, plate_height,
    strike_zone_top, strike_zone_bottom, ballcount,
    source_request_id, raw_json
)
SELECT
    pitch_id, game_id, plate_appearance_id, pitcher_id, batter_id,
    seqno, pitch_num, pitch_result_code, pitch_result_text,
    balls_after, strikes_after, outs_after,
    runner_on_first, runner_on_second, runner_on_third,
    pitch_type, speed_kph, batter_stance,
    x0, y0, z0, vx0, vy0, vz0, ax, ay, az,
    cross_plate_x, cross_plate_y, plate_height,
    strike_zone_top, strike_zone_bottom, ballcount,
    source_request_id, raw_json
FROM pitches_v1;

DROP TABLE pitches_v1;

CREATE INDEX idx_pitches_game_order ON pitches(game_id, seqno);
CREATE INDEX idx_pitches_plate_appearance
    ON pitches(plate_appearance_id, pitch_num);
CREATE INDEX idx_pitches_batter ON pitches(batter_id, game_id);
CREATE INDEX idx_pitches_pitcher ON pitches(pitcher_id, game_id);
