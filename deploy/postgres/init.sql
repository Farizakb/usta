-- Runs once on first start. Group roles are also created by migration 0001 (IF NOT EXISTS),
-- so order does not matter. Login passwords are local dev values, not secrets.
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_app') THEN CREATE ROLE usta_app NOLOGIN; END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'usta_purge') THEN CREATE ROLE usta_purge NOLOGIN; END IF;
END $$;
CREATE ROLE usta_app_login LOGIN PASSWORD 'usta_app_dev' IN ROLE usta_app;
CREATE DATABASE usta_test OWNER usta;
