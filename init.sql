-- Check if the database exists by using a PL/pgSQL block
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'vision_connect_dev ') THEN
        PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE vision_connect');
    END IF;
END
$$;

-- Connect to the target database
\c vision_connect;

-- Create extensions if they do not exist
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS hstore;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_sfcgal;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
CREATE EXTENSION IF NOT EXISTS address_standardizer;
CREATE EXTENSION IF NOT EXISTS address_standardizer_data_us;
CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

ALTER SYSTEM SET listen_addresses = '*';
