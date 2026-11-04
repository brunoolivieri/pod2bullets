-- SQLite Schema for pod2bullets (WAL mode enabled via connection manager)

CREATE TABLE IF NOT EXISTS subscription_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    rss_url TEXT NOT NULL UNIQUE,
    site_url TEXT,
    description TEXT,
    image_url TEXT,
    last_synced_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feed_list_members (
    feed_id INTEGER NOT NULL,
    list_id INTEGER NOT NULL,
    PRIMARY KEY (feed_id, list_id),
    FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE,
    FOREIGN KEY (list_id) REFERENCES subscription_lists(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER NOT NULL,
    guid TEXT NOT NULL,
    title TEXT NOT NULL,
    slug TEXT NOT NULL,
    published_at TEXT,
    duration_seconds INTEGER,
    audio_url TEXT NOT NULL,
    audio_ext TEXT NOT NULL DEFAULT 'mp3',
    image_url TEXT,
    summary TEXT,
    status TEXT NOT NULL DEFAULT 'available',
    local_audio_path TEXT,
    file_size_bytes INTEGER,
    sha256 TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(feed_id, guid),
    FOREIGN KEY (feed_id) REFERENCES feeds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transcripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    model_id TEXT NOT NULL,
    engine_name TEXT NOT NULL,
    language TEXT DEFAULT 'pt',
    plain_text_path TEXT NOT NULL,
    meta_json_path TEXT,
    char_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    duration_proc_seconds REAL,
    created_at TEXT NOT NULL,
    UNIQUE(episode_id, model_id),
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    transcript_id INTEGER,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_used TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    summary_path TEXT,
    duration_proc_seconds REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    episode_id INTEGER NOT NULL,
    model_id TEXT,
    progress_percent REAL NOT NULL DEFAULT 0.0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodes_feed ON episodes(feed_id);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
CREATE INDEX IF NOT EXISTS idx_transcripts_episode ON transcripts(episode_id);
CREATE INDEX IF NOT EXISTS idx_summaries_episode ON summaries(episode_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
