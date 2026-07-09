-- Acceptance optimization patch.
-- Run after 01_schema.sql, 02_data.sql and 03_routines_views_triggers.sql.
-- It makes integrity checks and query indexes explicit for course acceptance.

SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'book_retail_price_check') THEN
        ALTER TABLE ONLY "public"."book" ADD CONSTRAINT "book_retail_price_check" CHECK (retail_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'inventory_stock_quantity_check') THEN
        ALTER TABLE ONLY "public"."inventory" ADD CONSTRAINT "inventory_stock_quantity_check" CHECK (stock_quantity >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'purchase_detail_quantity_check') THEN
        ALTER TABLE ONLY "public"."purchase_detail" ADD CONSTRAINT "purchase_detail_quantity_check" CHECK (quantity > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'purchase_detail_price_check') THEN
        ALTER TABLE ONLY "public"."purchase_detail" ADD CONSTRAINT "purchase_detail_price_check" CHECK (purchase_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sales_detail_quantity_check') THEN
        ALTER TABLE ONLY "public"."sales_detail" ADD CONSTRAINT "sales_detail_quantity_check" CHECK (quantity > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sales_detail_price_check') THEN
        ALTER TABLE ONLY "public"."sales_detail" ADD CONSTRAINT "sales_detail_price_check" CHECK (sale_price >= 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check') THEN
        ALTER TABLE ONLY "public"."users" ADD CONSTRAINT "users_role_check" CHECK (role IN ('sys_admin', 'procurement_officer', 'warehouse_keeper', 'sales_agent', 'finance_officer'));
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS "idx_book_category_id" ON "public"."book" (category_id);
CREATE INDEX IF NOT EXISTS "idx_book_publisher_id" ON "public"."book" (publisher_id);
CREATE INDEX IF NOT EXISTS "idx_inventory_stock_quantity" ON "public"."inventory" (stock_quantity);
CREATE INDEX IF NOT EXISTS "idx_purchase_order_date" ON "public"."purchase_order" (purchase_date);
CREATE INDEX IF NOT EXISTS "idx_purchase_detail_order_id" ON "public"."purchase_detail" (order_id);
CREATE INDEX IF NOT EXISTS "idx_purchase_detail_book_id" ON "public"."purchase_detail" (book_id);
CREATE INDEX IF NOT EXISTS "idx_sales_order_date" ON "public"."sales_order" (sale_date);
CREATE INDEX IF NOT EXISTS "idx_sales_detail_order_id" ON "public"."sales_detail" (order_id);
CREATE INDEX IF NOT EXISTS "idx_sales_detail_book_id" ON "public"."sales_detail" (book_id);
CREATE INDEX IF NOT EXISTS "idx_users_role" ON "public"."users" (role);
