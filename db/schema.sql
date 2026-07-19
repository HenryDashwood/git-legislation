--
-- PostgreSQL database dump
--

\restrict britishlegislationschema

-- Dumped from database version 18.4 (Debian 18.4-1.pgdg13+1)
-- Dumped by pg_dump version 18.4 (Debian 18.4-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: drizzle; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA drizzle;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: __drizzle_migrations; Type: TABLE; Schema: drizzle; Owner: -
--

CREATE TABLE drizzle.__drizzle_migrations (
    id integer NOT NULL,
    hash text NOT NULL,
    created_at bigint
);


--
-- Name: __drizzle_migrations_id_seq; Type: SEQUENCE; Schema: drizzle; Owner: -
--

CREATE SEQUENCE drizzle.__drizzle_migrations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: __drizzle_migrations_id_seq; Type: SEQUENCE OWNED BY; Schema: drizzle; Owner: -
--

ALTER SEQUENCE drizzle.__drizzle_migrations_id_seq OWNED BY drizzle.__drizzle_migrations.id;


--
-- Name: document_files; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_files (
    id bigint NOT NULL,
    document_id text NOT NULL,
    version_id text,
    file_kind text NOT NULL,
    source_url text,
    object_key text,
    sha256 text,
    is_canonical boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT document_files_file_kind_check CHECK ((file_kind = ANY (ARRAY['clml_xml'::text, 'pdf'::text, 'markdown'::text, 'extracted_text'::text, 'report'::text, 'other'::text])))
);


--
-- Name: document_files_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_files_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_files_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_files_id_seq OWNED BY public.document_files.id;


--
-- Name: document_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_versions (
    id text NOT NULL,
    document_id text NOT NULL,
    version_kind text NOT NULL,
    snapshot_date date,
    source_uri text,
    source_object_key text,
    markdown_object_key text,
    source_sha256 text NOT NULL,
    markdown_sha256 text,
    word_count integer DEFAULT 0 NOT NULL,
    is_metadata_only boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    canonical_sha256 text,
    CONSTRAINT document_versions_check CHECK ((((version_kind = 'point_in_time'::text) AND (snapshot_date IS NOT NULL)) OR ((version_kind = ANY (ARRAY['enacted'::text, 'current'::text])) AND (snapshot_date IS NULL)))),
    CONSTRAINT document_versions_version_kind_check CHECK ((version_kind = ANY (ARRAY['enacted'::text, 'point_in_time'::text, 'current'::text]))),
    CONSTRAINT document_versions_word_count_check CHECK ((word_count >= 0))
);


--
-- Name: documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documents (
    id text NOT NULL,
    legislation_type text NOT NULL,
    year text NOT NULL,
    calendar_year integer,
    number text NOT NULL,
    title text NOT NULL,
    document_uri text NOT NULL,
    status text,
    extent text,
    source_path text[] NOT NULL,
    latest_version_id text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    legal_date date,
    legal_date_kind text,
    CONSTRAINT documents_legal_date_kind_check CHECK ((legal_date_kind = ANY (ARRAY['made'::text, 'enacted'::text])))
);


--
-- Name: fetch_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fetch_observations (
    id bigint NOT NULL,
    fetch_run_id bigint,
    document_id text,
    version_id text,
    source_url text NOT NULL,
    status text NOT NULL,
    status_code integer,
    source_sha256 text,
    error text,
    observed_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT fetch_observations_status_check CHECK ((status = ANY (ARRAY['fetched'::text, 'not_modified'::text, 'failed'::text, 'skipped'::text])))
);


--
-- Name: fetch_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fetch_observations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fetch_observations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fetch_observations_id_seq OWNED BY public.fetch_observations.id;


--
-- Name: fetch_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fetch_runs (
    id bigint NOT NULL,
    mode text NOT NULL,
    snapshot_date date,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    notes text,
    CONSTRAINT fetch_runs_mode_check CHECK ((mode = ANY (ARRAY['enacted'::text, 'point_in_time'::text, 'current'::text, 'publication_log'::text, 'publish'::text, 'other'::text])))
);


--
-- Name: fetch_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.fetch_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fetch_runs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.fetch_runs_id_seq OWNED BY public.fetch_runs.id;


--
-- Name: goose_db_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.goose_db_version (
    id integer NOT NULL,
    version_id bigint NOT NULL,
    is_applied boolean NOT NULL,
    tstamp timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: goose_db_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.goose_db_version ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.goose_db_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: pdf_fetch_failures; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pdf_fetch_failures (
    document_file_id bigint NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_attempt timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: provisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.provisions (
    id text NOT NULL,
    version_id text NOT NULL,
    document_id text NOT NULL,
    ordinal integer NOT NULL,
    provision_type text,
    number text,
    heading text NOT NULL,
    anchor text NOT NULL,
    markdown text NOT NULL,
    plain_text text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT provisions_ordinal_check CHECK ((ordinal > 0))
);


--
-- Name: storage_objects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_objects (
    key text NOT NULL,
    bucket text NOT NULL,
    sha256 text NOT NULL,
    byte_size bigint NOT NULL,
    content_type text,
    source_url text,
    fetched_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT storage_objects_byte_size_check CHECK ((byte_size >= 0))
);


--
-- Name: __drizzle_migrations id; Type: DEFAULT; Schema: drizzle; Owner: -
--

ALTER TABLE ONLY drizzle.__drizzle_migrations ALTER COLUMN id SET DEFAULT nextval('drizzle.__drizzle_migrations_id_seq'::regclass);


--
-- Name: document_files id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_files ALTER COLUMN id SET DEFAULT nextval('public.document_files_id_seq'::regclass);


--
-- Name: fetch_observations id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_observations ALTER COLUMN id SET DEFAULT nextval('public.fetch_observations_id_seq'::regclass);


--
-- Name: fetch_runs id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_runs ALTER COLUMN id SET DEFAULT nextval('public.fetch_runs_id_seq'::regclass);


--
-- Name: __drizzle_migrations __drizzle_migrations_pkey; Type: CONSTRAINT; Schema: drizzle; Owner: -
--

ALTER TABLE ONLY drizzle.__drizzle_migrations
    ADD CONSTRAINT __drizzle_migrations_pkey PRIMARY KEY (id);


--
-- Name: document_files document_files_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_files
    ADD CONSTRAINT document_files_pkey PRIMARY KEY (id);


--
-- Name: document_versions document_versions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_pkey PRIMARY KEY (id);


--
-- Name: documents documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);


--
-- Name: fetch_observations fetch_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_observations
    ADD CONSTRAINT fetch_observations_pkey PRIMARY KEY (id);


--
-- Name: fetch_runs fetch_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_runs
    ADD CONSTRAINT fetch_runs_pkey PRIMARY KEY (id);


--
-- Name: goose_db_version goose_db_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.goose_db_version
    ADD CONSTRAINT goose_db_version_pkey PRIMARY KEY (id);


--
-- Name: pdf_fetch_failures pdf_fetch_failures_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pdf_fetch_failures
    ADD CONSTRAINT pdf_fetch_failures_pkey PRIMARY KEY (document_file_id);


--
-- Name: provisions provisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provisions
    ADD CONSTRAINT provisions_pkey PRIMARY KEY (id);


--
-- Name: provisions provisions_version_id_ordinal_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provisions
    ADD CONSTRAINT provisions_version_id_ordinal_key UNIQUE (version_id, ordinal);


--
-- Name: storage_objects storage_objects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_objects
    ADD CONSTRAINT storage_objects_pkey PRIMARY KEY (key);


--
-- Name: document_files_document_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_files_document_idx ON public.document_files USING btree (document_id, file_kind);


--
-- Name: document_files_object_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_files_object_key_idx ON public.document_files USING btree (object_key);


--
-- Name: document_files_version_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_files_version_idx ON public.document_files USING btree (version_id, file_kind);


--
-- Name: document_versions_canonical_content_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_versions_canonical_content_idx ON public.document_versions USING btree (document_id, version_kind, canonical_sha256);


--
-- Name: document_versions_content_unique_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX document_versions_content_unique_idx ON public.document_versions USING btree (document_id, version_kind, source_sha256, markdown_sha256) WHERE (markdown_sha256 IS NOT NULL);


--
-- Name: document_versions_document_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_versions_document_idx ON public.document_versions USING btree (document_id, version_kind, snapshot_date);


--
-- Name: document_versions_markdown_object_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_versions_markdown_object_key_idx ON public.document_versions USING btree (markdown_object_key);


--
-- Name: document_versions_point_in_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_versions_point_in_time_idx ON public.document_versions USING btree (document_id, version_kind, snapshot_date) WHERE (snapshot_date IS NOT NULL);


--
-- Name: document_versions_source_object_key_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_versions_source_object_key_idx ON public.document_versions USING btree (source_object_key);


--
-- Name: document_versions_undated_unique_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX document_versions_undated_unique_idx ON public.document_versions USING btree (document_id, version_kind) WHERE (snapshot_date IS NULL);


--
-- Name: documents_latest_version_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_latest_version_idx ON public.documents USING btree (latest_version_id);


--
-- Name: documents_type_year_number_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documents_type_year_number_idx ON public.documents USING btree (legislation_type, calendar_year, number);


--
-- Name: fetch_observations_document_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fetch_observations_document_idx ON public.fetch_observations USING btree (document_id, observed_at);


--
-- Name: fetch_observations_run_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fetch_observations_run_idx ON public.fetch_observations USING btree (fetch_run_id, observed_at);


--
-- Name: fetch_observations_version_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fetch_observations_version_idx ON public.fetch_observations USING btree (version_id, observed_at);


--
-- Name: provisions_document_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX provisions_document_idx ON public.provisions USING btree (document_id);


--
-- Name: provisions_version_ordinal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX provisions_version_ordinal_idx ON public.provisions USING btree (version_id, ordinal);


--
-- Name: document_files document_files_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_files
    ADD CONSTRAINT document_files_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: document_files document_files_object_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_files
    ADD CONSTRAINT document_files_object_key_fkey FOREIGN KEY (object_key) REFERENCES public.storage_objects(key);


--
-- Name: document_files document_files_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_files
    ADD CONSTRAINT document_files_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.document_versions(id) ON DELETE CASCADE;


--
-- Name: document_versions document_versions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: document_versions document_versions_markdown_object_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_markdown_object_key_fkey FOREIGN KEY (markdown_object_key) REFERENCES public.storage_objects(key);


--
-- Name: document_versions document_versions_source_object_key_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_versions
    ADD CONSTRAINT document_versions_source_object_key_fkey FOREIGN KEY (source_object_key) REFERENCES public.storage_objects(key);


--
-- Name: documents documents_latest_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_latest_version_id_fkey FOREIGN KEY (latest_version_id) REFERENCES public.document_versions(id) ON DELETE SET NULL;


--
-- Name: fetch_observations fetch_observations_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_observations
    ADD CONSTRAINT fetch_observations_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE SET NULL;


--
-- Name: fetch_observations fetch_observations_fetch_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_observations
    ADD CONSTRAINT fetch_observations_fetch_run_id_fkey FOREIGN KEY (fetch_run_id) REFERENCES public.fetch_runs(id) ON DELETE SET NULL;


--
-- Name: fetch_observations fetch_observations_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fetch_observations
    ADD CONSTRAINT fetch_observations_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.document_versions(id) ON DELETE SET NULL;


--
-- Name: provisions provisions_document_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provisions
    ADD CONSTRAINT provisions_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;


--
-- Name: provisions provisions_version_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.provisions
    ADD CONSTRAINT provisions_version_id_fkey FOREIGN KEY (version_id) REFERENCES public.document_versions(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict britishlegislationschema

