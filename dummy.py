from sqlcoach.runner.explain_runner import is_mutating_statement

# Read-only queries (Allowed)
print(is_mutating_statement("SELECT * FROM users;"))            # False
print(is_mutating_statement("SELECT id FROM logs UNION SELECT id FROM audit;")) # False

# Mutating queries (Blocked)
print(is_mutating_statement("INSERT INTO users (name) VALUES ('Alice');")) # True
print(is_mutating_statement("UPDATE users SET active = true;")) # True
print(is_mutating_statement("DELETE FROM users WHERE id = 1;")) # True

# Malformed SQL / Generic commands (Default-Deny Blocked)
print(is_mutating_statement("SELEC * FRM broken_syntax;"))     # True
print(is_mutating_statement("SHOW tables;"))                    # True