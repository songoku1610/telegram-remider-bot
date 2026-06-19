use reminder_bot;
CREATE TABLE IF NOT EXISTS reminders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT,
    message TEXT,
    remind_at DATETIME,
    repeat_type VARCHAR(20), -- none, daily, weekly, monthly, yearly
    is_active BOOLEAN DEFAULT TRUE,
    is_lunar BOOLEAN DEFAULT FALSE,
    lunar_day TINYINT UNSIGNED DEFAULT NULL,
    lunar_month TINYINT UNSIGNED DEFAULT NULL,
    lunar_year SMALLINT UNSIGNED DEFAULT NULL,
    lunar_leap BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_remind_at ON reminders(remind_at);
CREATE INDEX idx_active ON reminders(is_active);
CREATE INDEX idx_active_remind ON reminders(is_active, remind_at);
