-- migration 0007
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id);
