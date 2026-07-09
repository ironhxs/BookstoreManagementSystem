# GaussDB Export Summary

Source version: gaussdb (GaussDB Kernel 505.2.1 build ff07bff6) compiled at 2024-12-27 09:22:42 commit 10161 last mr 21504 release
Exported public sequences: order_seq, purchase_detail_item_id_seq, sales_detail_item_id_seq
Exported public tables:
- book_category: 22 rows
- publisher: 31 rows
- purchase_order: 7 rows
- sales_order: 5 rows
- users: 6 rows
- book: 31 rows
- inventory: 13 rows
- purchase_detail: 17 rows
- sales_detail: 10 rows
Exported public views: v_bestsellers, v_low_quantity_books, v_num_book_cat, v_publisher_supply
Exported public functions: generate_purchase_order, generate_sales_order, get_book_stats_by_period, update_inventory_on_purchase, update_inventory_on_sale
Exported public triggers: trg_after_purchase, trg_before_sale
Acceptance optimization: CHECK constraints for price, quantity, stock and role values; indexes on foreign keys, order dates, stock quantity and user role.
