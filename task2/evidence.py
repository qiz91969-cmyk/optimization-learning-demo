"""Reviewed-location hints for existing teaching cases, not an automatic labeler."""


def field_evidence(case, public):
    text, supplement = public["description_en"], public["modeling_notes_en"]
    evidence = {}

    def add(path, source, quote, origin):
        body = text if source == "description_en" else supplement
        start = body.index(quote)
        evidence.setdefault(path, []).append({"source_field": source, "quote": quote,
            "start": start, "end": start + len(quote), "origin": origin, "review": "pending"})

    if case == "assignment":
        for path, quote in {
            "entities": "five workers W0,W1,W2,W3,W4",
            "parameters.tasks": "tasks T0,T1,T2,T3",
            "parameters.cost_matrix": "[[90,80,75,70],[35,85,55,65],[125,95,90,95],[45,110,95,115],[50,100,90,100]]",
            "objective": "Minimize total assignment cost.",
            "parameters.constraints": "Each task must be assigned to exactly one worker. Each worker can perform at most one task; one worker may remain idle.",
        }.items():
            add(path, "description_en", quote, "tutorial_paraphrase")
    else:
        phrases = {
            "printers": {"entities": "color printers and black and white printers",
                         "parameters.objective_coefficients": "Color printers generate a profit of $200 per printer while black and white printers generate a profit of $70 per printer.",
                         "parameters.upper_bounds": "at most 20 color printers per day while the black and white printer team can produce at most 30 black and white printers per day",
                         "parameters.constraints": "this machine can make at most 35 printers of either type each day",
                         "objective": "maximize the company's profit"},
            "bakery": {"entities": "bread and cookies", "objective": "maximize total profit",
                       "parameters.objective_coefficients": "The profit per loaf of bread is $5 and the profit per batch of cookies is $3.",
                       "parameters.constraints": "Each machine can run for at most 3000 hours per year. To bake a loaf of bread takes 1 hour in the stand mixer and 3 hours in the oven. A batch of cookies requires 0.5 hours in the mixer and 1 hour in the oven."},
            "advertising": {"entities": "(1) radio ads and (2) social media ads", "objective": "obtain maximum exposure",
                            "parameters.objective_coefficients": "The expected exposure, based on industry ratings, is 60,500 viewers for each radio ad. Additionally, the expected exposure for each social media ad is 50,000 viewers.",
                            "parameters.constraints": "Each radio ad costs $5,000; each social media ad costs $9,150.",
                            "parameters.lower_bounds": "at least 15 but no more than 40 radio ads should be ordered, and that at least 35 social media ads should be contracted",
                            "parameters.upper_bounds": "no more than 40 radio ads"},
        }[case]
        for path, quote in phrases.items():
            add(path, "description_en", quote, "public_statement")
        if case == "advertising":
            add("parameters.constraints", "description_en", "$250,000 advertising budget", "public_statement")
        add("parameters.variable_type", "modeling_notes_en", supplement.split(".")[0] + ".", "demo_supplement")
        if case != "advertising":
            add("parameters.lower_bounds", "modeling_notes_en", supplement.split(".")[0] + ".", "demo_supplement")
    add("units", "modeling_notes_en", supplement[supplement.index("Quantity unit:"):], "demo_supplement")
    if case == "assignment":
        add("parameters.variable_type", "modeling_notes_en", "Assignments are binary.", "demo_supplement")
    return evidence
