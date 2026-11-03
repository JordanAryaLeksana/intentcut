-- Readable project URLs: add a stable, unique slug beside the canonical UUID.
-- Explicit and transactional; apply only after backup, in one transaction.
-- Existing rows keep their UUID, name, jobs, and artifacts untouched.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug TEXT;

-- Backfill once: slugified name plus a short ID suffix guarantees
-- uniqueness even when existing projects share the same display name.
-- Accented names are transliterated (Café -> cafe) to match the slugs
-- the application generates; without the unaccent extension the plain
-- slugification still produces a valid, unique slug.
DO $$
BEGIN
    BEGIN
        CREATE EXTENSION IF NOT EXISTS unaccent;
    EXCEPTION WHEN OTHERS THEN
        NULL;
    END;
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'unaccent') THEN
        EXECUTE 'UPDATE projects
            SET slug = trim(both ''-'' FROM left(
                    trim(both ''-'' FROM regexp_replace(lower(trim(unaccent(name))), ''[^a-z0-9]+'', ''-'', ''g'')),
                    51
                )) || ''-'' || left(id::text, 8)
            WHERE slug IS NULL';
    ELSE
        EXECUTE 'UPDATE projects
            SET slug = trim(both ''-'' FROM left(
                    trim(both ''-'' FROM regexp_replace(lower(trim(name)), ''[^a-z0-9]+'', ''-'', ''g'')),
                    51
                )) || ''-'' || left(id::text, 8)
            WHERE slug IS NULL';
    END IF;
END $$;

-- Names with no ASCII letters/digits slugify to empty; give them a base.
UPDATE projects SET slug = 'project-' || left(id::text, 8)
WHERE slug LIKE '-%' OR slug = '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_slug ON projects (slug);
