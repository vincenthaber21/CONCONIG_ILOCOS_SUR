SET FOREIGN_KEY_CHECKS=0;
UPDATE members_segmentproductgroupdiscount m
SET discount_group_new_id = (SELECT id FROM inventory_productdiscountgroup WHERE code = m.discount_group)
WHERE discount_group_new_id IS NULL AND discount_group IS NOT NULL;
ALTER TABLE members_segmentproductgroupdiscount DROP COLUMN discount_group;
ALTER TABLE members_segmentproductgroupdiscount CHANGE COLUMN discount_group_new_id discount_group_id BIGINT NOT NULL;
SET FOREIGN_KEY_CHECKS=1;
