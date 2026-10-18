-- The electricity merchants' line on when to choose them (0022): it listed what the buyer gives as if the model
-- should ask for all of it, and the model asked for a meter type or a phone number the person had just said.
-- Now it names what is needed and says to ask only for what the person has not said.
UPDATE merchant
SET blurb = replace(
  blurb,
  ' Choose it only when the person names the company or the area; otherwise ask which. They give the meter number, say prepaid or postpaid (never assume it) and give a phone number.',
  ' Choose it when the person names the company or its area, else ask which. Needs the meter number, prepaid or postpaid (never assumed) and a phone number: ask only for what is not said.'
)
WHERE provider = 'vtpass' AND category = 'electricity';
