-- init_schema.sql
-- Database schema for GeoShardDB shards

-- Enable UUID extension if needed
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. users table
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    region VARCHAR(20) NOT NULL,
    subscription_type VARCHAR(20) NOT NULL, -- free, premium, enterprise
    department VARCHAR(50) DEFAULT 'general', -- engineering, sales, marketing, support, hr, finance
    status VARCHAR(20) DEFAULT 'active',      -- active, inactive, suspended
    login_count INTEGER DEFAULT 0,
    last_login TIMESTAMP,
    replicated BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. products table
CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50) NOT NULL,           -- cloud_compute, storage, database, analytics, security, ml_ai
    price_monthly DECIMAL(10,2) NOT NULL,
    region VARCHAR(20) NOT NULL,
    status VARCHAR(20) DEFAULT 'active',      -- active, deprecated, beta
    launch_date DATE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. support_tickets table
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    subject VARCHAR(300) NOT NULL,
    category VARCHAR(50) NOT NULL,           -- billing, technical, account, feature_request, bug_report
    priority VARCHAR(20) NOT NULL,           -- low, medium, high, critical
    status VARCHAR(20) DEFAULT 'open',        -- open, in_progress, resolved, closed
    region VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    resolved_at TIMESTAMP
);

-- 4. audit_logs table
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
    action VARCHAR(50) NOT NULL,             -- login, logout, data_export, permission_change, config_update
    resource VARCHAR(100) NOT NULL,
    region VARCHAR(20) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    success BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance & vector context retrieval
CREATE INDEX IF NOT EXISTS idx_users_region ON users(region);
CREATE INDEX IF NOT EXISTS idx_users_subscription ON users(subscription_type);
CREATE INDEX IF NOT EXISTS idx_products_region ON products(region);
CREATE INDEX IF NOT EXISTS idx_support_tickets_region ON support_tickets(region);
CREATE INDEX IF NOT EXISTS idx_support_tickets_priority ON support_tickets(priority);
CREATE INDEX IF NOT EXISTS idx_audit_logs_region ON audit_logs(region);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
