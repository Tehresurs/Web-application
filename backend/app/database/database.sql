-- ============================================
-- БАЗА ДАННЫХ AI EXCEL AGENT
-- Справочники:
-- 1. Сотрудники
-- 2. Объекты строительства
-- 3. Экипажи
-- ============================================

-- ============================================
-- 1. ДОЛЖНОСТИ
-- ============================================

CREATE TABLE positions (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(255) NOT NULL UNIQUE,

    -- Описание действий зависит от должности
    action_description TEXT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 2. ЭКИПАЖИ
-- ============================================

CREATE TABLE crews (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(100) NOT NULL UNIQUE,

    driver_full_name VARCHAR(255),

    driver_phone VARCHAR(30),

    vehicle_make VARCHAR(100),

    vehicle_plate VARCHAR(30),

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ============================================
-- 3. СОТРУДНИКИ
-- ============================================

CREATE TABLE employees (
    id BIGSERIAL PRIMARY KEY,

    full_name VARCHAR(255) NOT NULL,

    position_id BIGINT,

    phone VARCHAR(30),

    crew_id BIGINT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_employee_position
        FOREIGN KEY (position_id)
        REFERENCES positions(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_employee_crew
        FOREIGN KEY (crew_id)
        REFERENCES crews(id)
        ON DELETE SET NULL
);

-- Не разрешаем создать двух сотрудников
-- с полностью одинаковым ФИО
CREATE UNIQUE INDEX uq_employee_full_name
ON employees (LOWER(TRIM(full_name)));

-- ============================================
-- 4. КАТЕГОРИИ ОБЪЕКТОВ
-- ============================================

CREATE TABLE object_categories (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(255) NOT NULL UNIQUE
);

-- ============================================
-- 5. ОБЪЕКТЫ СТРОИТЕЛЬСТВА
-- ============================================

CREATE TABLE construction_objects (
    id BIGSERIAL PRIMARY KEY,

    name TEXT NOT NULL,

    category_id BIGINT,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_object_category
        FOREIGN KEY (category_id)
        REFERENCES object_categories(id)
        ON DELETE SET NULL
);

-- ============================================
-- 6. СПРАВОЧНИК ПО
-- ============================================

CREATE TABLE po_types (
    id BIGSERIAL PRIMARY KEY,

    name VARCHAR(255) NOT NULL UNIQUE
);

-- ============================================
-- 7. СТРОКИ ПО ДЛЯ ОБЪЕКТОВ
-- ============================================

CREATE TABLE object_po (
    id BIGSERIAL PRIMARY KEY,

    object_id BIGINT NOT NULL,

    po_id BIGINT NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_object_po_object
        FOREIGN KEY (object_id)
        REFERENCES construction_objects(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_object_po_type
        FOREIGN KEY (po_id)
        REFERENCES po_types(id)
        ON DELETE RESTRICT,

    -- Одно и то же ПО нельзя дважды
    -- назначить одному объекту
    CONSTRAINT uq_object_po
        UNIQUE (object_id, po_id)
);
