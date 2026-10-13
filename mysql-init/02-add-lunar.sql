-- Migration: thêm các cột hỗ trợ âm lịch vào bảng reminders.
-- Tương thích MySQL không hỗ trợ "ADD COLUMN IF NOT EXISTS".
-- Docker chỉ chạy script init trên database mới; các deployment hiện hữu được
-- migrate() trong telegrambot.py xử lý khi bot khởi động.

USE reminder_bot;

SET @table_schema := DATABASE();

SET @column_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = @table_schema AND table_name = 'reminders' AND column_name = 'is_lunar'
);
SET @sql := IF(@column_exists = 0, 'ALTER TABLE reminders ADD COLUMN is_lunar BOOLEAN DEFAULT FALSE', 'SELECT 1');
PREPARE statement FROM @sql;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @column_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = @table_schema AND table_name = 'reminders' AND column_name = 'lunar_day'
);
SET @sql := IF(@column_exists = 0, 'ALTER TABLE reminders ADD COLUMN lunar_day TINYINT UNSIGNED DEFAULT NULL', 'SELECT 1');
PREPARE statement FROM @sql;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @column_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = @table_schema AND table_name = 'reminders' AND column_name = 'lunar_month'
);
SET @sql := IF(@column_exists = 0, 'ALTER TABLE reminders ADD COLUMN lunar_month TINYINT UNSIGNED DEFAULT NULL', 'SELECT 1');
PREPARE statement FROM @sql;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @column_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = @table_schema AND table_name = 'reminders' AND column_name = 'lunar_year'
);
SET @sql := IF(@column_exists = 0, 'ALTER TABLE reminders ADD COLUMN lunar_year SMALLINT UNSIGNED DEFAULT NULL', 'SELECT 1');
PREPARE statement FROM @sql;
EXECUTE statement;
DEALLOCATE PREPARE statement;

SET @column_exists := (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = @table_schema AND table_name = 'reminders' AND column_name = 'lunar_leap'
);
SET @sql := IF(@column_exists = 0, 'ALTER TABLE reminders ADD COLUMN lunar_leap BOOLEAN DEFAULT FALSE', 'SELECT 1');
PREPARE statement FROM @sql;
EXECUTE statement;
DEALLOCATE PREPARE statement;
