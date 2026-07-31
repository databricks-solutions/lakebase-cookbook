-- 002: Seed data for the manufacturing telemetry schema.
--
-- Telemetry scenarios baked into the data:
--   * Robotic Arm RA-101:    motor temp rising 42°C → 87°C (critical) with escalating vibration
--   * Hydraulic Press HP-201: stable pressure, oil temp trending toward threshold
--   * CNC Mill CNC-301:       normal spindle temps, coolant flow dropping critically low
--   * Shrink Wrapper SW-402:  stable heater operation

-- Production Lines
INSERT INTO production_lines (line_name, facility, product_type, commissioned_date) VALUES
    ('Line A - Assembly', 'Plant North', 'automotive_parts', '2018-03-15'),
    ('Line B - Stamping', 'Plant North', 'metal_housings', '2015-07-22'),
    ('Line C - CNC Machining', 'Plant South', 'precision_components', '2020-11-01'),
    ('Line D - Packaging', 'Plant South', 'finished_goods', '2022-01-10');

-- Equipment
INSERT INTO equipment (line_id, equipment_name, equipment_type, manufacturer, model_number, install_date, last_maintenance) VALUES
    (1, 'Robotic Arm RA-101', 'robotic_arm', 'Fanuc', 'M-20iD/25', '2018-03-15', '2026-05-10'),
    (1, 'Conveyor Belt CB-A1', 'conveyor', 'Hytrol', 'EZLogic-200', '2018-03-15', '2026-04-20'),
    (2, 'Hydraulic Press HP-201', 'press', 'Schuler', 'TwinServo-2500', '2015-07-22', '2026-05-01'),
    (2, 'Stamping Die Changer DC-202', 'die_changer', 'Komatsu', 'H2F-300', '2016-02-10', '2026-03-15'),
    (3, 'CNC Mill CNC-301', 'cnc_mill', 'Haas', 'VF-4SS', '2020-11-01', '2026-05-25'),
    (3, 'CNC Lathe CNC-302', 'cnc_lathe', 'Mazak', 'QT-250MSY', '2020-11-01', '2026-05-25'),
    (4, 'Palletizer PK-401', 'palletizer', 'ABB', 'IRB-660', '2022-01-10', '2026-04-30'),
    (4, 'Shrink Wrapper SW-402', 'wrapper', 'Lantech', 'ST-900', '2022-01-10', '2026-05-15');

-- Sensors
INSERT INTO sensors (equipment_id, sensor_name, sensor_type, unit, min_threshold, max_threshold) VALUES
    (1, 'RA-101 Motor Temp', 'temperature', '°C', 20.00, 85.00),
    (1, 'RA-101 Vibration', 'vibration', 'mm/s', 0.00, 7.50),
    (1, 'RA-101 Current Draw', 'current', 'A', 0.50, 15.00),
    (2, 'CB-A1 Belt Speed', 'speed', 'm/min', 5.00, 30.00),
    (2, 'CB-A1 Motor Temp', 'temperature', '°C', 20.00, 75.00),
    (3, 'HP-201 Hydraulic Pressure', 'pressure', 'bar', 50.00, 350.00),
    (3, 'HP-201 Oil Temp', 'temperature', '°C', 30.00, 65.00),
    (3, 'HP-201 Vibration', 'vibration', 'mm/s', 0.00, 10.00),
    (5, 'CNC-301 Spindle Temp', 'temperature', '°C', 25.00, 70.00),
    (5, 'CNC-301 Spindle Vibration', 'vibration', 'mm/s', 0.00, 5.00),
    (5, 'CNC-301 Coolant Flow', 'flow_rate', 'L/min', 2.00, 12.00),
    (6, 'CNC-302 Spindle Temp', 'temperature', '°C', 25.00, 70.00),
    (6, 'CNC-302 Chuck Pressure', 'pressure', 'bar', 10.00, 45.00),
    (7, 'PK-401 Arm Vibration', 'vibration', 'mm/s', 0.00, 6.00),
    (7, 'PK-401 Cycle Counter', 'counter', 'cycles', 0.00, 999999.00),
    (8, 'SW-402 Heater Temp', 'temperature', '°C', 150.00, 220.00);

-- Telemetry Readings (recent readings showing normal and anomalous data)
INSERT INTO telemetry_readings (sensor_id, reading_time, value, quality) VALUES
    -- RA-101 Motor Temp (normal, then rising)
    (1, '2026-06-05 08:00:00', 42.30, 'good'),
    (1, '2026-06-05 08:15:00', 43.10, 'good'),
    (1, '2026-06-05 08:30:00', 48.70, 'good'),
    (1, '2026-06-05 08:45:00', 62.50, 'warning'),
    (1, '2026-06-05 09:00:00', 78.90, 'warning'),
    (1, '2026-06-05 09:15:00', 87.20, 'critical'),
    -- RA-101 Vibration (escalating)
    (2, '2026-06-05 08:00:00', 2.10, 'good'),
    (2, '2026-06-05 08:30:00', 3.40, 'good'),
    (2, '2026-06-05 09:00:00', 6.80, 'warning'),
    (2, '2026-06-05 09:15:00', 9.10, 'critical'),
    -- HP-201 Hydraulic Pressure (stable)
    (6, '2026-06-05 08:00:00', 245.00, 'good'),
    (6, '2026-06-05 08:30:00', 248.30, 'good'),
    (6, '2026-06-05 09:00:00', 250.10, 'good'),
    -- HP-201 Oil Temp (slowly rising)
    (7, '2026-06-05 08:00:00', 48.20, 'good'),
    (7, '2026-06-05 08:30:00', 52.10, 'good'),
    (7, '2026-06-05 09:00:00', 58.90, 'warning'),
    (7, '2026-06-05 09:30:00', 63.40, 'warning'),
    -- CNC-301 Spindle Temp (normal)
    (9, '2026-06-05 08:00:00', 38.50, 'good'),
    (9, '2026-06-05 08:30:00', 39.20, 'good'),
    (9, '2026-06-05 09:00:00', 40.10, 'good'),
    -- CNC-301 Coolant Flow (dropping)
    (11, '2026-06-05 08:00:00', 8.50, 'good'),
    (11, '2026-06-05 08:30:00', 6.20, 'good'),
    (11, '2026-06-05 09:00:00', 3.10, 'warning'),
    (11, '2026-06-05 09:30:00', 1.80, 'critical'),
    -- SW-402 Heater Temp (stable)
    (16, '2026-06-05 08:00:00', 185.00, 'good'),
    (16, '2026-06-05 08:30:00', 186.20, 'good'),
    (16, '2026-06-05 09:00:00', 184.80, 'good');

-- Alerts
INSERT INTO alerts (sensor_id, alert_time, severity, alert_type, message, acknowledged, resolved_at) VALUES
    (1, '2026-06-05 09:15:00', 'critical', 'threshold_breach', 'Motor temperature 87.2°C exceeds max threshold 85°C', FALSE, NULL),
    (2, '2026-06-05 09:15:00', 'critical', 'threshold_breach', 'Vibration 9.1 mm/s exceeds max threshold 7.5 mm/s', FALSE, NULL),
    (7, '2026-06-05 09:30:00', 'warning', 'threshold_approach', 'Oil temperature 63.4°C approaching max threshold 65°C', TRUE, NULL),
    (11, '2026-06-05 09:30:00', 'critical', 'threshold_breach', 'Coolant flow 1.8 L/min below min threshold 2.0 L/min', FALSE, NULL),
    (1, '2026-06-04 14:20:00', 'warning', 'threshold_approach', 'Motor temperature 80.1°C approaching max threshold', TRUE, '2026-06-04 15:00:00'),
    (6, '2026-06-03 11:00:00', 'warning', 'anomaly_detected', 'Pressure spike to 340 bar detected', TRUE, '2026-06-03 11:30:00');

-- Work Orders
INSERT INTO work_orders (equipment_id, alert_id, created_at, assigned_to, status, priority, description, completed_at) VALUES
    (1, 1, '2026-06-05 09:20:00', 'Mike Torres', 'in_progress', 'critical', 'Robotic arm RA-101 overheating — shut down and inspect motor bearings', NULL),
    (1, 2, '2026-06-05 09:20:00', 'Mike Torres', 'open', 'critical', 'Excessive vibration on RA-101 — check joint calibration and gearbox', NULL),
    (5, 4, '2026-06-05 09:35:00', 'Sarah Chen', 'open', 'high', 'CNC-301 coolant flow critically low — inspect pump and filter', NULL),
    (3, 3, '2026-06-05 09:45:00', 'James Park', 'open', 'medium', 'HP-201 oil temp trending high — schedule oil change and filter replacement', NULL),
    (1, 5, '2026-06-04 14:25:00', 'Mike Torres', 'completed', 'medium', 'Cleaned air vents around RA-101 motor housing', '2026-06-04 16:00:00'),
    (3, 6, '2026-06-03 11:05:00', 'James Park', 'completed', 'low', 'Inspected pressure relief valve — found minor seal wear, replaced', '2026-06-03 13:30:00');
