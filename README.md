# VISION CONNECT

## *Technical Documentation*

This documentation covers the **Vision Connect** project, whose main objectives are:

* Vehicle management
* Geolocation and tracking
* Remote vehicle control

---

# 🚀 Backend Installation - Vision Connect

## 📌 Prerequisites

* **Docker** installed on your machine
* **Git** installed to clone the project

---

## 🛠 Step 1: Installing and Launching the Backend

### 1️⃣ **Clone the project**

```bash
git clone <REPO_URL>
cd vision-connect-backend
```

### 2️⃣ **Start the Docker containers**

Run the following command from the root of the project:

```bash
docker compose up --build
```

📌 **This will:**

* Build and start the necessary containers
* Install the required dependencies

### 3️⃣ **Access the Django container**

In a separate terminal, enter the container:

```bash
docker compose exec -ti vision-connect-django bash
```

Once inside, you should see a prompt similar to:

```bash
root@017ed9fd8050:/home/backend#
```

<span style="color: red; font-size: 18px; font-weight: bold;">
🚨 All commands must be executed **inside** the Django container. 🚨  
</span>

Here are some example commands to run in the container:

```bash
root@017ed9fd8050:/home/backend# python manage.py createsuperuser
root@017ed9fd8050:/home/backend# pip install django-rest-api
root@017ed9fd8050:/home/backend# pip freeze > requirements.txt
```

---

## 🔑 Step 2: Create a Superuser

Still inside the Django container, run:

```bash
python manage.py createsuperuser
```

Follow the prompts to set up an admin account.

---

## 🗂 Step 3: Create the Administrator User

In the **"Administrator"** menu, please fill in the required information to create an admin user by clicking the **"Add Administrator User"** button.

---

## 🌍 Step 4: Import Initial Data into the Database

This step imports device types, the list of countries, and the default intervention zone into the PostgreSQL database.

### 📥 One-Time Import Command

```bash
docker compose exec django python manage.py populate_device || { echo "❌ Error: populate_device"; exit 1; } && \
docker compose exec django python manage.py populate_countries || { echo "❌ Error: populate_countries"; exit 1; } && \
docker compose exec django python manage.py populate_zones_and_companies || { echo "❌ Error: populate_zones_and_companies"; exit 1; }
```

---

## ✅ Accessing the Login Interface

Once all steps are completed, you can log in:

* **Superuser**: use the account created via `python manage.py createsuperuser`
* **Administrator**: use the account created in **Step 3** (via the web interface or SQL query)

---

## 🎯 Conclusion

🚀 **Your backend is now ready to use!**
You can start testing and developing on **Vision Connect**.

---

Let me know if you'd like the same document in Markdown or PDF format!
