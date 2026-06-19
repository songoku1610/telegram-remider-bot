-- Migration: thêm các cột hỗ trợ âm lịch vào bảng reminders
-- Chạy file này cho các deployment đã có sẵn database

USE reminder_bot;

ALTER TABLE reminders
    ADD COLUMN IF NOT EXISTS is_lunar   BOOLEAN        DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS lunar_day  TINYINT UNSIGNED DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS lunar_month TINYINT UNSIGNED DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS lunar_year SMALLINT UNSIGNED DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS lunar_leap BOOLEAN        DEFAULT FALSE;
