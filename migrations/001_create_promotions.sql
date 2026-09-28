-- Promotions API schema. This migration is intentionally data-free.
CREATE TABLE IF NOT EXISTS promotions (
    id VARCHAR(50) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    subtitle VARCHAR(255),
    description TEXT NOT NULL,
    image_url TEXT NOT NULL,
    images JSONB DEFAULT '[]'::jsonb,
    hero_image_url TEXT,
    badge VARCHAR(100) DEFAULT 'PROMOTION',
    discount_tag VARCHAR(100),
    valid_until VARCHAR(100),
    link_url VARCHAR(255) DEFAULT '/#products',
    cta_text VARCHAR(100) DEFAULT 'ดูสินค้าโปรโมชั่น',
    secondary_cta_text VARCHAR(100),
    secondary_link_url VARCHAR(255),
    is_featured BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_promotions_active_sort
    ON promotions (is_active, sort_order);
