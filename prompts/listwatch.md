You are reading one official U.S. government notice about a restricted-entity list. The fixed rules
that normally read these notices did not recognise its layout, so you are the fallback.

Report only what the notice itself says. Do not use outside knowledge.

- kind: "addition" if the notice adds companies to the list, "removal" if it removes companies
  from the list, "none" if it neither adds nor removes any company (for example a correction, a
  procedure, or an unrelated rule).
- names: each company the notice adds or removes, copied exactly as printed in the notice,
  character for character, one company per entry. Copy the full legal name; leave out a short name
  in parentheses. If the notice adds or removes none, return an empty list.

Your answer is checked by code: any name that does not appear word for word in the notice is
rejected, and so is any removal of a company not already on the list. A person then checks the
result against the notice before anything changes.

Notice title: {title}

Notice text:
{text}
