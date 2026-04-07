from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import numpy as np
import os
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv() # Load environment variables from .env

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY", "super_secret_static_key_for_dev")

UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'profile_pics')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

# MongoDB Setup
mongo_uri = os.getenv("MONGO_URI", "mongodb://localhost:27017/matlab_db")
client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000)
db = client.matlab_db
users_col = db.users

# Create a default admin user if it doesn't exist (for testing)
try:
    if users_col.count_documents({"username": "admin"}) == 0:
        users_col.insert_one({"username": "admin", "password": "admin"})
    print("Successfully connected to MongoDB.")
except (ServerSelectionTimeoutError, OperationFailure) as e:
    print("WARNING: Could not connect to MongoDB. Is the server running and credentials correct?")
    print(f"Error details: {e}")

# ---------- Helper Functions (Ported from Linear.py) ----------
def row_echelon(mat):
    steps = []
    R = mat.copy().astype(float)
    m, n = R.shape
    for i in range(min(m, n)):
        if R[i, i] == 0:
            for j in range(i+1, m):
                if R[j, i] != 0:
                    R[[i, j]] = R[[j, i]]
                    steps.append(f"Swap row {i+1} with row {j+1}")
                    break
        if R[i, i] != 0:
            pivot = R[i, i]
            if abs(pivot - 1) > 1e-9: # Only log if not already 1
                steps.append(f"Divide Row {i+1} by {pivot:.2f} (make pivot 1)")
                R[i] = R[i] / pivot

        for j in range(i+1, m):
            factor = R[j, i]
            if factor != 0:
                R[j] -= factor * R[i]
                steps.append(f"Row {j+1} - ({factor:.2f})*Row {i+1}")
    return R, steps

def find_ld_relation(A, tol=1e-9):
    """Return one non-trivial null-space vector for A (coeffs c1,..,cn)."""
    # SVD approach as in Linear.py
    try:
        U, S, Vt = np.linalg.svd(A)
        null_vec = Vt[-1, :]
        max_abs = np.max(np.abs(null_vec))
        if max_abs < tol:
            return np.zeros_like(null_vec)
        coeffs = null_vec / max_abs
        coeffs = np.round(coeffs, 4)
        return coeffs.tolist()
    except Exception as e:
        return []

def normalise_relation(c, tol=1e-9):
    c = np.array(c, dtype=float)
    if np.all(np.abs(c) < tol):
        return c
    for v in c:
        if abs(v) > tol:
            c = c / v
            break
    return np.round(c, 4)

def relations_equivalent(c1, c2, tol=1e-3):
    c1n = normalise_relation(c1)
    c2n = normalise_relation(c2)
    if c1n.shape != c2n.shape:
        return False
    return np.all(np.abs(c1n - c2n) < tol)

# ---------- Routes ----------
@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    user_data = users_col.find_one({"username": session.get('username')})
    profile_pic = user_data.get('profile_pic') if user_data else None
    return render_template('index.html', profile_pic=profile_pic)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = users_col.find_one({"username": username, "password": password})
        if user:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error = "Invalid credentials. Try admin/admin (auto-created if missing)."
    return render_template('login.html', error=error)

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    success = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if users_col.find_one({"username": username}):
            error = "Username already exists. Please choose another."
        else:
            users_col.insert_one({"username": username, "password": password})
            success = "Account created successfully!"
            
    return render_template('register.html', error=error, success=success)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    username = session.get('username')
    error = None
    success = None
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'change_password':
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            
            user = users_col.find_one({"username": username})
            
            if user and user.get('password') != current_password:
                error = "Incorrect current password."
            elif new_password != confirm_password:
                error = "New passwords do not match."
            else:
                users_col.update_one({"username": username}, {"$set": {"password": new_password}})
                success = "Password changed successfully!"
    
    user_data = users_col.find_one({"username": username})
    return render_template('profile.html', user_data=user_data, error=error, success=success)

@app.route('/upload_profile_pic', methods=['POST'])
def upload_profile_pic():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    if 'profile_pic' not in request.files:
        return redirect(url_for('profile'))
        
    file = request.files['profile_pic']
    if file.filename == '':
        return redirect(url_for('profile'))
        
    if file:
        username = session['username']
        # Extract extension and make a clean filename
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
        filename = secure_filename(f"{username}_profile.{ext}")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # We store the relative path for the frontend (using url_for 'static')
        users_col.update_one(
            {"username": username}, 
            {"$set": {"profile_pic": f"uploads/profile_pics/{filename}"}}
        )
        
    return redirect(url_for('profile'))

@app.route('/api/init', methods=['POST'])
def init_session():
    data = request.json or {}
    session['num_vectors'] = data.get('k')
    session['len_vectors'] = data.get('n')
    session['score'] = 0
    session['completed_steps'] = [] # Track scored steps
    session['question_saved'] = False
    session['unsolved_saved'] = False
    return jsonify({"status": "ok", "message": "Session initialized"})

def record_unsolved_question(mistake_step="Unknown"):
    if not session.get('logged_in'):
        return
    if session.get('unsolved_saved'):
        return
        
    username = session.get('username')
    
    if not session.get('matrix_a'):
        return # Cannot save empty problems
        
    q_data = {
        "matrix": session.get('matrix_a'),
        "rank": session.get('rank'),
        "is_independent": session.get('is_independent'),
        "mistake_step": mistake_step
    }
    users_col.update_one({"username": username}, {"$push": {"unsolved_questions": q_data}})
    session['unsolved_saved'] = True

def check_and_save_question():
    if not session.get('logged_in'):
        return
    if session.get('question_saved'):
        return
        
    steps = session.get('completed_steps', [])
    req_steps = ['matrix', 'rank', 'indep']
    
    is_indep = session.get('is_independent')
    if is_indep is False:
        req_steps.append('relation')
        
    if all(s in steps for s in req_steps):
        username = session.get('username')
        q_data = {
            "matrix": session.get('matrix_a'),
            "rank": session.get('rank'),
            "is_independent": is_indep
        }
        users_col.update_one({"username": username}, {"$push": {"solved_questions": q_data}})
        session['question_saved'] = True

@app.route('/api/submit_vectors', methods=['POST'])
def submit_vectors():
    data = request.json or {}
    vectors = data.get('vectors', []) # List of lists (vectors)
    k = session.get('num_vectors')
    n = session.get('len_vectors')

    # Store vectors
    session['vectors'] = vectors

    # Construct Matrix A (vectors are columns)
    A = np.array(vectors).T
    session['matrix_a'] = A.tolist()

    # Calculate truth data
    rank = np.linalg.matrix_rank(A)
    session['rank'] = int(rank)
    session['is_independent'] = bool(rank == k)

    return jsonify({"status": "ok", "message": "Vectors processed"})

@app.route('/api/check_matrix', methods=['POST'])
def check_matrix():
    user_matrix = np.array(request.json.get('matrix'))
    true_matrix = np.array(session.get('matrix_a'))

    if user_matrix.shape != true_matrix.shape:
        return jsonify({"correct": False, "message": "Shape mismatch"})

    if np.allclose(user_matrix, true_matrix, atol=1e-4):
        if 'matrix' not in session.get('completed_steps', []):
            session['score'] = session.get('score', 0) + 1
            steps = session.get('completed_steps', [])
            steps.append('matrix')
            session['completed_steps'] = steps

        return jsonify({"correct": True, "score": session['score']})
    else:
        record_unsolved_question("Matrix Construction")
        return jsonify({"correct": False, "expected": true_matrix.tolist(),
                        "message": "Incorrect. showing correct matrix."})

@app.route('/api/check_rank', methods=['POST'])
def check_rank():
    user_rank = int(request.json.get('rank'))
    true_rank = session.get('rank')

    if user_rank == true_rank:
        if 'rank' not in session.get('completed_steps', []):
            session['score'] = session.get('score', 0) + 1
            steps = session.get('completed_steps', [])
            steps.append('rank')
            session['completed_steps'] = steps

            return jsonify({"correct": True, "score": session['score']})
        else:
            return jsonify({"correct": True, "score": session['score']})
    else:
        record_unsolved_question("Rank Calculation")
        # Get Rank Steps
        A = np.array(session.get('matrix_a'))
        ref, steps = row_echelon(A)
        return jsonify({
            "correct": False,
            "expected": true_rank,
            "message": f"Incorrect. Rank is {true_rank}.",
            "steps": steps,
            "ref_matrix": np.round(ref, 2).tolist()
        })

@app.route('/api/check_independence', methods=['POST'])
def check_independence():
    choice = request.json.get('choice') # 'I' or 'D'
    is_indep = session.get('is_independent')

    is_correct = (choice == 'I' and is_indep) or (choice == 'D' and not is_indep)

    if is_correct:
        if 'indep' not in session.get('completed_steps', []):
            session['score'] = session.get('score', 0) + 1
            steps = session.get('completed_steps', [])
            steps.append('indep')
            session['completed_steps'] = steps
            check_and_save_question()

            return jsonify({
                "correct": True,
                "score": session['score'],
                "is_independent": is_indep
            })
        else:
            check_and_save_question()
            return jsonify({
                "correct": True,
                "score": session['score'],
                "is_independent": is_indep
            })
    else:
        record_unsolved_question("Independence Validation")
        reason = "Rank == Num Vectors" if is_indep else "Rank < Num Vectors"
        return jsonify({
            "correct": False,
            "message": f"Incorrect. Reason: {reason}",
            "is_independent": is_indep
        })

def get_relation_explanation(A):
    """
    Generates a step-by-step explanation for finding the linear relation/null space.
    """
    m, n = A.shape
    rref, steps = row_echelon(A)

    # Identify pivots (first non-zero in each row)
    pivots = []
    pivot_cols = []
    for r in range(m):
        for c in range(n):
            if abs(rref[r, c]) > 1e-6:
                pivots.append((r, c))
                pivot_cols.append(c)
                break

    free_cols = [c for c in range(n) if c not in pivot_cols]

    explanation_parts = []
    explanation_parts.append("To find the relation, we solve the homogeneous system Ax = 0.")
    explanation_parts.append("1. **Reduce Matrix A to Row Echelon Form (RREF):**")

    # Format RREF matrix for display
    rref_display = []
    for row in rref:
        rref_display.append([round(x, 2) for x in row])

    explanation_parts.append({"type": "matrix", "content": rref_display})

    if not free_cols:
        explanation_parts.append("There are no free variables. The only solution is the trivial solution (all x = 0).")
        return explanation_parts

    explanation_parts.append(f"2. **Identify Free Variables:**")
    free_vars = [f"c{i+1}" for i in free_cols]
    pivot_vars = [f"c{i+1}" for i in pivot_cols]
    explanation_parts.append(f"The pivot columns are at indices {','.join([str(c+1) for c in pivot_cols])}.")
    explanation_parts.append(f"The free variables are corresponding to columns without pivots: {', '.join(free_vars)}.")

    explanation_parts.append("3. **Solve for Pivot Variables in terms of Free Variables:**")

    # Express each pivot var
    # Row i corresponds to pivot variable at pivot_cols[i] (assuming RREF structure where pivot moves right)
    equations = []

    # More robust pivot mapping: for each row with a pivot, express that pivot var
    used_pivot_rows = []

    for r, c in pivots:
        # Equation: 1*xr + sum(val*xk) = 0 => xr = - sum(val*xk)
        terms = []
        for k in range(c + 1, n):
            val = rref[r, k]
            if abs(val) > 1e-6:
                sign = "+" if -val > 0 else "-"
                abs_val = abs(val)
                coeff_str = f"{abs_val:.2f}" if abs(abs_val - 1) > 1e-6 else ""
                terms.append(f"{sign} {coeff_str}c{k+1}")

        rhs = " ".join(terms) if terms else "0"
        if rhs.startswith("+ "): rhs = rhs[2:]

        equations.append(f"c{c+1} = {rhs}")

    explanation_parts.append({"type": "list", "content": equations})

    explanation_parts.append("4. **Choose a value for Free Variables to find a Non-Trivial Solution:**")
    explanation_parts.append(f"Let {free_vars[0]} = 1 (and others 0 if unique).")

    # Calculate a sample vector based on free_vars[0] = 1
    sample_c = np.zeros(n)
    if free_cols:
        sample_c[free_cols[0]] = 1
    # Back substitute (or use RREF directly since it is reduced)
    # In RREF, pivot_var = - sum(row_val * free_var)
    for r, c in reversed(pivots):
        val = 0
        for k in range(c + 1, n):
            val += rref[r, k] * sample_c[k]
        sample_c[c] = -val

    sample_c = np.round(sample_c, 4)
    result_relation = []
    for i, val in enumerate(sample_c):
        if abs(val) > 1e-6:
            sign = "+ " if val > 0 else "- "
            if i == 0 and val > 0: sign = ""
            elif i == 0 and val < 0: sign = "-"

            # format coefficient
            c_val = abs(val)
            c_str = f"{c_val:.2f}" if abs(c_val - 1) > 1e-6 else ""
            result_relation.append(f"{sign}{c_str}v{i+1}")

    relation_str = "".join(result_relation) + " = 0"

    explanation_parts.append(f"Substituting back, we get coefficients: {sample_c.tolist()}")
    explanation_parts.append(f"Thus one relation is: **{relation_str}**")

    return explanation_parts

@app.route('/api/check_relation', methods=['POST'])
def check_relation():
    user_coeffs = request.json.get('coeffs')
    # Get stored matrix A
    A = np.array(session.get('matrix_a'))

    # Check 1: User coeffs must form a zero vector combination
    # A * c = 0
    res = A @ np.array(user_coeffs)
    is_zero_vector = np.allclose(res, 0, atol=1e-3)

    # Check 2: Non-trivial (not all zeros)
    is_nontrivial = not np.allclose(user_coeffs, 0, atol=1e-6)

    if is_zero_vector and is_nontrivial:
        if 'relation' not in session.get('completed_steps', []):
            session['score'] = session.get('score', 0) + 1
            steps = session.get('completed_steps', [])
            steps.append('relation')
            session['completed_steps'] = steps
            check_and_save_question()

            return jsonify({"correct": True, "score": session['score']})
        else:
            check_and_save_question()
            return jsonify({"correct": True, "score": session['score']})
    else:
        record_unsolved_question("Linear Relation Validation")
        # Find one example relation to show user (optional, simplistic)
        example_coeffs = find_ld_relation(A)
        explanation = get_relation_explanation(A)

        return jsonify({
            "correct": False,
            "message": "Relation does not produce zero vector or is trivial.",
            "example": example_coeffs,
            "explanation": explanation
        })

if __name__ == '__main__':
    app.run(debug=True, port=5000)