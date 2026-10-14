-- Television and electricity through VTpass (docs/commerce.md, "Providers"): the merchants of the `vtpass`
-- provider, and the columns of existing tables that bills need.
--
-- A bill's offers are not rows. A bouquet and its price are VTpass's, read from its `service-variations` each
-- time (commerce/vtpass_offers.py), so a price that VTpass changes is the price a quote is made at; only the
-- merchants are rows, so that an account check and a quote can name one (their foreign keys) and a quote that
-- names one keeps it (0020's triggers).

-- What a provider found beyond the holder: facts to show, and the limits and amounts it priced from. A check
-- stays immutable (0020).
ALTER TABLE account_check ADD COLUMN detail TEXT NOT NULL DEFAULT '{}'
  CHECK (json_valid(detail) AND json_type(detail) = 'object');

-- The simulated VTpass keeps the smartcard or meter a bill was ordered for, and whether a television
-- subscription was renewed or changed (vtpass/sim_bills.py).
ALTER TABLE sim_vtpass ADD COLUMN billers_code TEXT;
ALTER TABLE sim_vtpass ADD COLUMN subscription_type TEXT;

-- The merchants. The id is VTpass's serviceID. `min_kobo` is the smallest amount any quote may be for (NGN 50,
-- checkout/amount_floor.py); a meter's own least comes from its account check. `max_kobo` is 10^13, the value
-- that means the merchant states no most (commerce/model.py): VTpass publishes none, and the limits that apply
-- are the person's own.
INSERT INTO merchant (id, provider, name, category, status, requires_link, blurb, min_kobo, max_kobo, fee_label,
  fee_kobo, checks_account, fields, created_at, updated_at) VALUES
('dstv', 'vtpass', 'DStv', 'tv', 'live', 0,
 'Pays a DStv subscription. Choose it when the person says DStv or a DStv bouquet. They give the smartcard number; renewing keeps the bouquet they have, and changing names another.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"smartcard","label":"Smartcard number","kind":"digits","required":true,"min":10,"max":12,"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('gotv', 'vtpass', 'GOtv', 'tv', 'live', 0,
 'Pays a GOtv subscription. Choose it when the person says GOtv or a GOtv bouquet. They give the smartcard (IUC) number; renewing keeps the bouquet they have, and changing names another.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"smartcard","label":"Smartcard number","kind":"digits","required":true,"min":10,"max":12,"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('startimes', 'vtpass', 'StarTimes', 'tv', 'live', 0,
 'Pays a StarTimes subscription. Choose it when the person says StarTimes. They give the smartcard number and the bouquet.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"smartcard","label":"Smartcard number","kind":"digits","required":true,"min":10,"max":12,"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('showmax', 'vtpass', 'Showmax', 'tv', 'live', 0,
 'Pays a Showmax subscription for a phone number, which is the subscriber. It has no account check. Choose it when the person says Showmax.',
 5000, 10000000000000, 'Service fee', 0, 0,
 '[{"name":"phone","label":"Subscriber phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('ikeja-electric', 'vtpass', 'Ikeja Electric (IKEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Ikeja Electric: Lagos mainland, Ikeja, Alimosho, Agege and Ikorodu. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('eko-electric', 'vtpass', 'Eko Electricity (EKEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Eko Electricity: Lagos Island, Lekki, Victoria Island, Ikoyi, Ajah and Festac. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('kano-electric', 'vtpass', 'Kano Electricity (KEDCO)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Kano Electricity (KEDCO): Kano, Katsina and Jigawa. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('portharcourt-electric', 'vtpass', 'Port Harcourt Electricity (PHED)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Port Harcourt Electricity (PHED): Rivers, Bayelsa, Akwa Ibom and Cross River. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('jos-electric', 'vtpass', 'Jos Electricity (JED)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Jos Electricity (JED): Plateau, Bauchi, Benue and Gombe. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('ibadan-electric', 'vtpass', 'Ibadan Electricity (IBEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Ibadan Electricity (IBEDC): Oyo, Ogun, Osun and Kwara. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('kaduna-electric', 'vtpass', 'Kaduna Electric (KAEDCO)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Kaduna Electric (KAEDCO): Kaduna, Sokoto, Kebbi and Zamfara. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('abuja-electric', 'vtpass', 'Abuja Electricity (AEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Abuja Electricity (AEDC): the FCT, Niger, Kogi and Nasarawa. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('enugu-electric', 'vtpass', 'Enugu Electricity (EEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Enugu Electricity (EEDC): Enugu, Abia, Anambra, Ebonyi and Imo. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('benin-electric', 'vtpass', 'Benin Electricity (BEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Benin Electricity (BEDC): Edo, Delta, Ondo and Ekiti. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('aba-electric', 'vtpass', 'Aba Power (ABA)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Aba Power, in Aba, Abia. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000),
('yola-electric', 'vtpass', 'Yola Electricity (YEDC)', 'electricity', 'live', 0,
 'Buys electricity for a meter of Yola Electricity (YEDC): Adamawa, Taraba, Borno and Yobe. The person gives the meter number and says prepaid or postpaid.',
 5000, 10000000000000, 'Service fee', 0, 1,
 '[{"name":"meter_number","label":"Meter number","kind":"digits","required":true,"min":6,"max":13,"account":true},{"name":"meter_type","label":"Meter type","kind":"choice","required":true,"options":["prepaid","postpaid"],"account":true},{"name":"phone","label":"Phone number","kind":"text","required":true,"max":20}]',
 1791936000000, 1791936000000);
