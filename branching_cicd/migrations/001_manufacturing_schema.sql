-- 001: Manufacturing telemetry baseline schema.
--
-- Models a plant floor: production lines own equipment, equipment carries
-- sensors, sensors emit telemetry readings; threshold breaches raise alerts,
-- and alerts spawn maintenance work orders.
--
--   production_lines → equipment → sensors → telemetry_readings
--                                       ↘ alerts → work_orders

-- Production lines in the facility
CREATE TABLE IF NOT EXISTS production_lines (
    line_id SERIAL PRIMARY KEY,
    line_name VARCHAR(100) NOT NULL,
    facility VARCHAR(100) NOT NULL,
    product_type VARCHAR(50) NOT NULL,
    commissioned_date DATE
);

-- Equipment on each production line
CREATE TABLE IF NOT EXISTS equipment (
    equipment_id SERIAL PRIMARY KEY,
    line_id INTEGER NOT NULL REFERENCES production_lines(line_id),
    equipment_name VARCHAR(150) NOT NULL,
    equipment_type VARCHAR(50) NOT NULL,
    manufacturer VARCHAR(100),
    model_number VARCHAR(100),
    install_date DATE,
    last_maintenance DATE
);

-- Sensors attached to equipment
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id SERIAL PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(equipment_id),
    sensor_name VARCHAR(100) NOT NULL,
    sensor_type VARCHAR(50) NOT NULL,
    unit VARCHAR(20) NOT NULL,
    min_threshold DECIMAL(10,2),
    max_threshold DECIMAL(10,2),
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- Telemetry readings from sensors
CREATE TABLE IF NOT EXISTS telemetry_readings (
    reading_id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(sensor_id),
    reading_time TIMESTAMP NOT NULL DEFAULT NOW(),
    value DECIMAL(12,4) NOT NULL,
    quality VARCHAR(20) NOT NULL DEFAULT 'good'
);

-- Equipment alerts triggered by threshold breaches
CREATE TABLE IF NOT EXISTS alerts (
    alert_id SERIAL PRIMARY KEY,
    sensor_id INTEGER NOT NULL REFERENCES sensors(sensor_id),
    alert_time TIMESTAMP NOT NULL DEFAULT NOW(),
    severity VARCHAR(20) NOT NULL,
    alert_type VARCHAR(50) NOT NULL,
    message TEXT,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at TIMESTAMP
);

-- Maintenance work orders
CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id SERIAL PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment(equipment_id),
    alert_id INTEGER REFERENCES alerts(alert_id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    assigned_to VARCHAR(100),
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    priority VARCHAR(10) NOT NULL DEFAULT 'medium',
    description TEXT,
    completed_at TIMESTAMP
);

-- Hot-path indexes: time-series reads per sensor, open alerts, equipment lookups
CREATE INDEX IF NOT EXISTS ix_telemetry_readings_sensor_time
    ON telemetry_readings (sensor_id, reading_time DESC);
CREATE INDEX IF NOT EXISTS ix_alerts_sensor_time
    ON alerts (sensor_id, alert_time DESC);
CREATE INDEX IF NOT EXISTS ix_work_orders_equipment
    ON work_orders (equipment_id);
