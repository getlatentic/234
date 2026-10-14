-- The simulated directory (docs/commerce.md, "Providers"): four invented merchants of different kinds, so the
-- generic path is exercised end to end with no real shop behind it. Mama Put is the restaurant of
-- checkout/src/checkout/food/menu.py, whose menu is listed here with the same ids, names, prices and tags
-- (tests/test_commerce_directory.py keeps the two the same while both exist). None of these names a real
-- business. Prices are in kobo; every row is stamped 2026-10-14 00:00 UTC.

INSERT INTO merchant (id, name, category, status, blurb, min_kobo, max_kobo, fee_label, fee_kobo, checks_account,
  fields, created_at, updated_at) VALUES
('mama-put-yaba', 'Mama Put Yaba (simulated)', 'food', 'live',
 'An invented Lagos canteen: rice, soups, suya and drinks, delivered in seven areas. Choose it for a cooked meal or a drink.',
 100000, 3000000, 'Delivery', 120000, 0,
 '[{"name":"area","label":"Delivery area","kind":"choice","required":true,"options":["Yaba","Surulere","Ikeja GRA","Maryland","Lekki Phase 1","Victoria Island","Ikoyi"]},{"name":"note","label":"Note for the rider","kind":"text","required":false,"max":120}]',
 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'LagosMed Pharmacy (simulated)', 'health', 'live',
 'An invented Lagos pharmacy for everyday medicines and first aid, delivered in three areas. Choose it for over-the-counter items; it sells no prescription medicine.',
 100000, 2000000, 'Delivery', 100000, 0,
 '[{"name":"area","label":"Delivery area","kind":"choice","required":true,"options":["Yaba","Surulere","Ikeja GRA"]}]',
 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'Ikeja Fresh Grocer (simulated)', 'grocery', 'live',
 'An invented Lagos grocer for staples and fresh food to cook at home: rice, garri, eggs, vegetables. Delivered in three areas.',
 200000, 5000000, 'Delivery', 150000, 0,
 '[{"name":"area","label":"Delivery area","kind":"choice","required":true,"options":["Ikeja GRA","Maryland","Yaba"]}]',
 1791936000000, 1791936000000),
('metrogo-transit', 'MetroGo Transit (simulated)', 'service', 'beta',
 'An invented city transit card. The card number is checked first and the holder''s name is shown for the person to confirm. The person says how much credit to add.',
 50000, 5000000, 'Fee', 0, 1,
 '[{"name":"card_number","label":"Card number","kind":"digits","required":true,"min":8,"max":10}]',
 1791936000000, 1791936000000);

INSERT INTO offer (merchant_id, id, name, description, tags, price_kind, price_kobo, min_kobo, max_kobo, available,
  max_quantity, option_groups, position, created_at, updated_at) VALUES
('mama-put-yaba', 'jollof-chicken', 'Jollof rice with fried chicken', 'Party jollof, one piece of chicken, fried plantain', 'rice chicken meal', 'fixed', 450000, NULL, NULL, 1, 10, '[]', 1, 1791936000000, 1791936000000),
('mama-put-yaba', 'fried-rice-dodo', 'Fried rice, dodo and grilled chicken', 'Fried rice with peppered chicken and dodo', 'rice chicken meal', 'fixed', 480000, NULL, NULL, 1, 10, '[]', 2, 1791936000000, 1791936000000),
('mama-put-yaba', 'egusi-pounded-yam', 'Egusi soup with pounded yam', 'Egusi with assorted meat, two wraps of pounded yam', 'soup swallow meal spicy', 'fixed', 520000, NULL, NULL, 1, 10, '[]', 3, 1791936000000, 1791936000000),
('mama-put-yaba', 'amala-ewedu', 'Amala, ewedu and gbegiri', 'With assorted meat and stew', 'swallow soup meal spicy', 'fixed', 420000, NULL, NULL, 0, 10, '[]', 4, 1791936000000, 1791936000000),
('mama-put-yaba', 'beef-suya', 'Beef suya, 200g', 'Grilled beef with onions, tomato and yaji', 'suya beef grill spicy snack', 'fixed', 350000, NULL, NULL, 1, 10, '[]', 5, 1791936000000, 1791936000000),
('mama-put-yaba', 'catfish-pepper-soup', 'Catfish pepper soup', 'Hot pepper soup with fresh catfish', 'soup fish spicy', 'fixed', 600000, NULL, NULL, 1, 10, '[]', 6, 1791936000000, 1791936000000),
('mama-put-yaba', 'moi-moi', 'Moi moi, 2 wraps', 'Steamed bean pudding with egg', 'beans snack side', 'fixed', 150000, NULL, NULL, 1, 10, '[]', 7, 1791936000000, 1791936000000),
('mama-put-yaba', 'puff-puff', 'Puff puff, 6 pieces', 'Sweet fried dough balls', 'snack sweet side', 'fixed', 100000, NULL, NULL, 1, 10, '[]', 8, 1791936000000, 1791936000000),
('mama-put-yaba', 'zobo', 'Zobo, 500ml', 'Chilled hibiscus drink with ginger', 'drink', 'fixed', 80000, NULL, NULL, 1, 10, '[]', 9, 1791936000000, 1791936000000),
('mama-put-yaba', 'chapman', 'Chapman, 500ml', 'Fruity non-alcoholic cocktail', 'drink sweet', 'fixed', 180000, NULL, NULL, 1, 10, '[]', 10, 1791936000000, 1791936000000),
('mama-put-yaba', 'water', 'Bottled water, 75cl', 'Still water', 'drink', 'fixed', 30000, NULL, NULL, 1, 10, '[]', 11, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'paracetamol-500', 'Paracetamol 500mg, 20 tablets', 'Pain and fever relief', 'pain fever headache tablets', 'fixed', 90000, NULL, NULL, 1, 6, '[]', 1, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'vitamin-c', 'Vitamin C 1000mg, 10 effervescent tablets', 'Orange flavour', 'vitamin supplement tablets', 'fixed', 250000, NULL, NULL, 1, 6, '[]', 2, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'ors-sachets', 'Oral rehydration salts, 5 sachets', 'For dehydration from diarrhoea', 'ors dehydration diarrhoea', 'fixed', 120000, NULL, NULL, 1, 6, '[]', 3, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'hand-sanitiser', 'Hand sanitiser', 'Alcohol gel', 'sanitiser hygiene', 'fixed', 90000, NULL, NULL, 1, 6,
 '[{"id":"size","label":"Size","min":1,"max":1,"choices":[{"id":"100ml","label":"100ml","delta_kobo":0},{"id":"250ml","label":"250ml","delta_kobo":110000}]}]',
 4, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'plasters', 'Adhesive plasters, box of 40', 'Assorted sizes', 'plaster first aid', 'fixed', 150000, NULL, NULL, 1, 6, '[]', 5, 1791936000000, 1791936000000),
('lagosmed-pharmacy', 'malaria-test', 'Malaria rapid test kit', 'Single test', 'malaria test', 'fixed', 200000, NULL, NULL, 0, 6, '[]', 6, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'rice-5kg', 'Long grain rice, 5kg', 'Parboiled', 'rice staple', 'fixed', 980000, NULL, NULL, 1, 5, '[]', 1, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'garri-2kg', 'Garri, 2kg', 'White ijebu garri', 'garri staple cassava', 'fixed', 240000, NULL, NULL, 1, 5, '[]', 2, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'eggs-crate', 'Eggs, crate of 30', 'Farm eggs', 'eggs protein', 'fixed', 450000, NULL, NULL, 1, 4, '[]', 3, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'tomatoes', 'Fresh tomatoes', 'Basket of ripe tomatoes', 'tomato vegetable stew', 'fixed', 180000, NULL, NULL, 1, 5,
 '[{"id":"size","label":"Basket","min":1,"max":1,"choices":[{"id":"small","label":"Small","delta_kobo":0},{"id":"large","label":"Large","delta_kobo":150000}]}]',
 4, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'plantain-bunch', 'Plantain, a bunch', 'Ripe or unripe', 'plantain dodo', 'fixed', 200000, NULL, NULL, 1, 5, '[]', 5, 1791936000000, 1791936000000),
('ikeja-fresh-grocer', 'palm-oil-1l', 'Palm oil, 1 litre', 'Bottled', 'oil palm cooking', 'fixed', 320000, NULL, NULL, 1, 5, '[]', 6, 1791936000000, 1791936000000),
('metrogo-transit', 'card-topup', 'Transit card top-up', 'Any amount of credit for the customer''s card', 'transit card credit topup', 'open', NULL, NULL, NULL, 1, 1, '[]', 1, 1791936000000, 1791936000000),
('metrogo-transit', 'group-booking', 'Group booking deposit', 'Reserve a group trip with a deposit', 'group booking deposit transit', 'range', NULL, 100000, 2000000, 1, 1, '[]', 2, 1791936000000, 1791936000000),
('metrogo-transit', 'card-replacement', 'Replacement card fee', 'For a lost or damaged card', 'replacement card lost transit', 'fixed', 250000, NULL, NULL, 1, 1, '[]', 3, 1791936000000, 1791936000000);

INSERT INTO sim_merchant_account (merchant_id, reference, holder_name, due_kobo) VALUES
('metrogo-transit', '10012345', 'ADEBAYO OLUWASEUN FOLA', 1250000),
('metrogo-transit', '10067890', 'CHINWE NNEKA OKAFOR', 0),
('metrogo-transit', '10099999', 'MALLAM ABUBAKAR SANI', 480000);
