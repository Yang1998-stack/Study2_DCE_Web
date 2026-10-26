-- Additive D1 schema. Never DROP, REPLACE or rewrite historical answers.
CREATE TABLE IF NOT EXISTS study_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS designs (version TEXT PRIMARY KEY, task_hash TEXT NOT NULL, tasks_json TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS participants (
 id TEXT PRIMARY KEY, token_digest TEXT NOT NULL UNIQUE,
 mode TEXT NOT NULL CHECK(mode IN ('demo','pilot','formal')),
 group_code INTEGER NOT NULL CHECK(group_code BETWEEN 1 AND 4), block TEXT NOT NULL CHECK(block IN ('A','B')),
 swap_bits TEXT NOT NULL, task_order TEXT NOT NULL, created_at TEXT NOT NULL,
 stimulus_started_at TEXT, stimulus_end_at TEXT, attributes_seen_at TEXT, dce_started_at TEXT, dce_completed_at TEXT,
 completed_at TEXT, age INTEGER, gender TEXT, education TEXT, online_purchase TEXT, plant_based_purchase TEXT,
 manip_visual TEXT, manip_ai TEXT, additional_answers TEXT NOT NULL DEFAULT '{}',
 design_version TEXT NOT NULL REFERENCES designs(version), task_hash TEXT NOT NULL,
 source_instance TEXT NOT NULL, source_participant_id TEXT NOT NULL, stimulus_versions TEXT, consent_version TEXT,
 validation_status TEXT NOT NULL DEFAULT 'unreviewed' CHECK(validation_status IN ('unreviewed','valid','excluded')),
 provenance TEXT NOT NULL DEFAULT 'live', UNIQUE(source_instance,source_participant_id,mode)
);
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS participants_dataset ON participants(mode,design_version,created_at);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS task_views (
 participant_id TEXT NOT NULL REFERENCES participants(id), task_id TEXT NOT NULL, started_at TEXT NOT NULL,
 a_json TEXT, b_json TEXT, content_version TEXT, PRIMARY KEY(participant_id,task_id)
);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS choices (
 participant_id TEXT NOT NULL REFERENCES participants(id), task_id TEXT NOT NULL,
 displayed_choice TEXT NOT NULL CHECK(displayed_choice IN ('A','B','N')), answered_at TEXT NOT NULL,
 process_json TEXT, PRIMARY KEY(participant_id,task_id)
);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS detail_views (
 event_id TEXT PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES participants(id),task_id TEXT NOT NULL,
 alternative TEXT NOT NULL CHECK(alternative IN ('A','B')),kind TEXT NOT NULL CHECK(kind IN ('environment','quality')),
 level INTEGER NOT NULL CHECK(level IN (0,1)),content_version TEXT NOT NULL,opened_at TEXT NOT NULL,
 shown_at TEXT,updated_at TEXT NOT NULL,closed_at TEXT,duration_ms INTEGER NOT NULL DEFAULT 0 CHECK(duration_ms>=0),
 close_reason TEXT NOT NULL DEFAULT ''
);
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS details_participant ON detail_views(participant_id,task_id,alternative);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS invitations (digest TEXT PRIMARY KEY,mode TEXT NOT NULL CHECK(mode IN ('pilot','formal')),used_by TEXT UNIQUE,created_at TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS admin_sessions (digest TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires TEXT NOT NULL,credential_fingerprint TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS auth_failures (key TEXT PRIMARY KEY,window_at TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS import_batches (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,mode TEXT NOT NULL,design_version TEXT NOT NULL,status TEXT NOT NULL,owner TEXT NOT NULL,report TEXT NOT NULL,committed_at TEXT);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS archive_chunks (archive_id TEXT NOT NULL,filename TEXT NOT NULL,part INTEGER NOT NULL,data_base64 TEXT NOT NULL,PRIMARY KEY(archive_id,filename,part));
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS backups (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,mode TEXT NOT NULL,design_version TEXT NOT NULL,sha256 TEXT NOT NULL,bytes INTEGER NOT NULL,reason TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS review_log (id INTEGER PRIMARY KEY,participant_id TEXT NOT NULL,status TEXT NOT NULL,note TEXT NOT NULL,reviewed_at TEXT NOT NULL);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS qf_submissions (
 participant_id TEXT PRIMARY KEY REFERENCES participants(id),submission_uuid TEXT NOT NULL UNIQUE,
 survey_mode TEXT NOT NULL,design_version TEXT NOT NULL,target_url TEXT,payload_json TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','success','failed','uncertain')),attempt_count INTEGER NOT NULL DEFAULT 0,
 cycle_attempts INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,next_attempt_at TEXT,
 last_attempt_at TEXT,success_at TEXT,last_http_status INTEGER,last_error TEXT,in_flight_token TEXT,in_flight_at TEXT,
 confirmation TEXT,retryable INTEGER NOT NULL DEFAULT 0
);
-- statement-breakpoint
CREATE INDEX IF NOT EXISTS qf_due ON qf_submissions(status,survey_mode,next_attempt_at);
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS qf_attempts (id INTEGER PRIMARY KEY,participant_id TEXT NOT NULL REFERENCES qf_submissions(participant_id),attempt_number INTEGER NOT NULL,started_at TEXT NOT NULL,finished_at TEXT,http_status INTEGER,outcome TEXT NOT NULL,error_summary TEXT,response_summary TEXT,payload_sha256 TEXT NOT NULL,UNIQUE(participant_id,attempt_number));
-- statement-breakpoint
CREATE TABLE IF NOT EXISTS qf_actions (id INTEGER PRIMARY KEY,participant_id TEXT,action TEXT NOT NULL,note TEXT NOT NULL,created_at TEXT NOT NULL,actor TEXT NOT NULL);
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS immutable_assignment BEFORE UPDATE OF group_code,block,swap_bits,task_order,design_version,task_hash,mode ON participants
WHEN NEW.group_code!=OLD.group_code OR NEW.block!=OLD.block OR NEW.swap_bits!=OLD.swap_bits OR NEW.task_order!=OLD.task_order OR NEW.design_version!=OLD.design_version OR NEW.task_hash!=OLD.task_hash OR NEW.mode!=OLD.mode
BEGIN SELECT RAISE(ABORT,'实验分配不可覆盖'); END;
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS immutable_choice BEFORE UPDATE ON choices BEGIN SELECT RAISE(ABORT,'原始选择不可覆盖'); END;
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS validate_native_choice BEFORE INSERT ON choices
WHEN NOT EXISTS(SELECT 1 FROM choices WHERE participant_id=NEW.participant_id AND task_id=NEW.task_id)
AND (SELECT provenance FROM participants WHERE id=NEW.participant_id) NOT LIKE 'import:%'
BEGIN
 SELECT CASE WHEN (SELECT completed_at IS NOT NULL OR attributes_seen_at IS NULL FROM participants WHERE id=NEW.participant_id) THEN RAISE(ABORT,'实验阶段不正确') END;
 SELECT CASE WHEN NEW.task_id IS NOT (SELECT json_extract(task_order,'$['||(SELECT COUNT(*) FROM choices WHERE participant_id=NEW.participant_id)||']') FROM participants WHERE id=NEW.participant_id) THEN RAISE(ABORT,'题目顺序不一致') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM task_views WHERE participant_id=NEW.participant_id AND task_id=NEW.task_id) THEN RAISE(ABORT,'本题尚未展示') END;
END;
-- statement-breakpoint
CREATE TRIGGER IF NOT EXISTS set_dce_complete AFTER INSERT ON choices
WHEN (SELECT provenance FROM participants WHERE id=NEW.participant_id) NOT LIKE 'import:%'
BEGIN UPDATE participants SET dce_completed_at=COALESCE(dce_completed_at,NEW.answered_at) WHERE id=NEW.participant_id AND (SELECT COUNT(*) FROM choices WHERE participant_id=NEW.participant_id)=json_array_length(task_order); END;
