// 认证相关的JavaScript模块

// API配置
const AUTH_API = {
    register: '/api/auth/register',
    login: '/api/auth/login',
    logout: '/api/auth/logout',
    me: '/api/auth/me',
    verify: '/api/auth/verify'
};

// 工具函数
const AuthUtils = {
    // 显示错误消息
    showError: function(message, elementId = 'errorAlert') {
        const errorAlert = document.getElementById(elementId);
        const errorMessage = document.getElementById('errorMessage');
        if (errorAlert && errorMessage) {
            errorMessage.textContent = message;
            errorAlert.style.display = 'flex';
            // 3秒后自动隐藏
            setTimeout(() => {
                errorAlert.style.display = 'none';
            }, 5000);
        }
    },

    // 显示成功消息
    showSuccess: function(message, elementId = 'successAlert') {
        const successAlert = document.getElementById(elementId);
        const successMessage = document.getElementById('successMessage');
        if (successAlert && successMessage) {
            successMessage.textContent = message;
            successAlert.style.display = 'flex';
            // 3秒后自动隐藏
            setTimeout(() => {
                successAlert.style.display = 'none';
            }, 3000);
        }
    },

    // 隐藏所有警告
    hideAlerts: function() {
        const errorAlert = document.getElementById('errorAlert');
        const successAlert = document.getElementById('successAlert');
        if (errorAlert) errorAlert.style.display = 'none';
        if (successAlert) successAlert.style.display = 'none';
    },

    // 显示字段错误
    showFieldError: function(fieldName, message) {
        const errorElement = document.getElementById(fieldName + 'Error');
        if (errorElement) {
            errorElement.textContent = message;
        }
    },

    // 清除字段错误
    clearFieldErrors: function() {
        const errorElements = document.querySelectorAll('.error-message');
        errorElements.forEach(element => {
            element.textContent = '';
        });
    },

    // 设置按钮加载状态
    setButtonLoading: function(buttonId, loading) {
        const button = document.getElementById(buttonId);
        const buttonText = button.querySelector('.button-text');
        const loadingSpinner = button.querySelector('.loading-spinner');
        
        if (loading) {
            button.disabled = true;
            buttonText.style.display = 'none';
            loadingSpinner.style.display = 'flex';
        } else {
            button.disabled = false;
            buttonText.style.display = 'block';
            loadingSpinner.style.display = 'none';
        }
    },

    // 验证邮箱格式
    validateEmail: function(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    },

    // 验证用户名
    validateUsername: function(username) {
        return username && username.length >= 3;
    },

    // 验证密码
    validatePassword: function(password) {
        return password && password.length >= 6;
    },

    // 存储令牌
    setToken: function(token) {
        localStorage.setItem('auth_token', token);
    },

    // 获取令牌
    getToken: function() {
        return localStorage.getItem('auth_token');
    },

    // 移除令牌
    removeToken: function() {
        localStorage.removeItem('auth_token');
    },

    // 检查是否已登录
    isLoggedIn: function() {
        return !!this.getToken();
    }
};

// API请求函数
const AuthAPI = {
    // 发送请求
    request: async function(url, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json'
            }
        };

        // 添加认证头
        const token = AuthUtils.getToken();
        if (token) {
            defaultOptions.headers['Authorization'] = `Bearer ${token}`;
        }

        const finalOptions = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...options.headers
            }
        };

        try {
            const response = await fetch(url, finalOptions);
            const data = await response.json();
            
            if (!response.ok) {
                throw new Error(data.detail || '请求失败');
            }
            
            return data;
        } catch (error) {
            console.error('API请求错误:', error);
            throw error;
        }
    },

    // 用户注册
    register: async function(userData) {
        return await this.request(AUTH_API.register, {
            method: 'POST',
            body: JSON.stringify(userData)
        });
    },

    // 用户登录
    login: async function(credentials) {
        return await this.request(AUTH_API.login, {
            method: 'POST',
            body: JSON.stringify(credentials)
        });
    },

    // 用户登出
    logout: async function() {
        return await this.request(AUTH_API.logout, {
            method: 'POST'
        });
    },

    // 获取当前用户信息
    getCurrentUser: async function() {
        return await this.request(AUTH_API.me);
    },

    // 验证令牌
    verifyToken: async function() {
        return await this.request(AUTH_API.verify);
    }
};

// 密码可见性切换
function initPasswordToggle() {
    const passwordToggles = document.querySelectorAll('.password-toggle');
    
    passwordToggles.forEach(toggle => {
        toggle.addEventListener('click', function() {
            const passwordInput = this.parentElement.querySelector('input[type="password"], input[type="text"]');
            const eyeIcon = this.querySelector('.eye-icon');
            
            if (passwordInput.type === 'password') {
                passwordInput.type = 'text';
                eyeIcon.innerHTML = `
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                `;
            } else {
                passwordInput.type = 'password';
                eyeIcon.innerHTML = `
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                `;
            }
        });
    });
}

// 初始化登录页面
function initLogin() {
    const loginForm = document.getElementById('loginForm');
    if (!loginForm) return;

    // 初始化密码切换
    initPasswordToggle();

    // 检查是否已登录
    if (AuthUtils.isLoggedIn()) {
        // 验证令牌有效性
        AuthAPI.verifyToken()
            .then(() => {
                // 令牌有效，跳转到主页
                window.location.href = 'index.html';
            })
            .catch(() => {
                // 令牌无效，清除并继续登录流程
                AuthUtils.removeToken();
            });
    }

    // 表单提交处理
    loginForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // 清除之前的错误
        AuthUtils.clearFieldErrors();
        AuthUtils.hideAlerts();
        
        // 获取表单数据
        const formData = new FormData(loginForm);
        const username = formData.get('username').trim();
        const password = formData.get('password');
        
        // 基本验证
        let hasError = false;
        
        if (!username) {
            AuthUtils.showFieldError('username', '请输入用户名或邮箱');
            hasError = true;
        }
        
        if (!password) {
            AuthUtils.showFieldError('password', '请输入密码');
            hasError = true;
        }
        
        if (hasError) return;
        
        // 设置加载状态
        AuthUtils.setButtonLoading('loginButton', true);
        
        try {
            // 发送登录请求
            const response = await AuthAPI.login({
                username: username,
                password: password
            });
            
            // 保存令牌
            AuthUtils.setToken(response.access_token);
            
            // 显示成功消息
            AuthUtils.showSuccess('登录成功！正在跳转...');
            
            // 跳转到主页
            setTimeout(() => {
                window.location.href = 'index.html';
            }, 1000);
            
        } catch (error) {
            AuthUtils.showError(error.message || '登录失败，请检查用户名和密码');
        } finally {
            AuthUtils.setButtonLoading('loginButton', false);
        }
    });
}

// 初始化注册页面
function initRegister() {
    const registerForm = document.getElementById('registerForm');
    if (!registerForm) return;

    // 初始化密码切换
    initPasswordToggle();

    // 检查是否已登录
    if (AuthUtils.isLoggedIn()) {
        // 验证令牌有效性
        AuthAPI.verifyToken()
            .then(() => {
                // 令牌有效，跳转到主页
                window.location.href = 'index.html';
            })
            .catch(() => {
                // 令牌无效，清除并继续注册流程
                AuthUtils.removeToken();
            });
    }

    // 实时验证
    const usernameInput = document.getElementById('username');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const confirmPasswordInput = document.getElementById('confirmPassword');

    // 用户名验证
    usernameInput.addEventListener('blur', function() {
        const username = this.value.trim();
        if (username && !AuthUtils.validateUsername(username)) {
            AuthUtils.showFieldError('username', '用户名至少需要3个字符');
        } else {
            AuthUtils.showFieldError('username', '');
        }
    });

    // 邮箱验证
    emailInput.addEventListener('blur', function() {
        const email = this.value.trim();
        if (email && !AuthUtils.validateEmail(email)) {
            AuthUtils.showFieldError('email', '请输入有效的邮箱地址');
        } else {
            AuthUtils.showFieldError('email', '');
        }
    });

    // 密码验证
    passwordInput.addEventListener('blur', function() {
        const password = this.value;
        if (password && !AuthUtils.validatePassword(password)) {
            AuthUtils.showFieldError('password', '密码至少需要6个字符');
        } else {
            AuthUtils.showFieldError('password', '');
        }
        
        // 如果确认密码已填写，重新验证
        if (confirmPasswordInput.value) {
            validatePasswordMatch();
        }
    });

    // 确认密码验证
    function validatePasswordMatch() {
        const password = passwordInput.value;
        const confirmPassword = confirmPasswordInput.value;
        
        if (confirmPassword && password !== confirmPassword) {
            AuthUtils.showFieldError('confirmPassword', '两次输入的密码不一致');
            return false;
        } else {
            AuthUtils.showFieldError('confirmPassword', '');
            return true;
        }
    }

    confirmPasswordInput.addEventListener('blur', validatePasswordMatch);

    // 表单提交处理
    registerForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        // 清除之前的错误
        AuthUtils.clearFieldErrors();
        AuthUtils.hideAlerts();
        
        // 获取表单数据
        const formData = new FormData(registerForm);
        const username = formData.get('username').trim();
        const email = formData.get('email').trim();
        const password = formData.get('password');
        const confirmPassword = formData.get('confirmPassword');
        const agreeTerms = formData.get('agreeTerms');
        
        // 验证
        let hasError = false;
        
        if (!AuthUtils.validateUsername(username)) {
            AuthUtils.showFieldError('username', '用户名至少需要3个字符');
            hasError = true;
        }
        
        if (!AuthUtils.validateEmail(email)) {
            AuthUtils.showFieldError('email', '请输入有效的邮箱地址');
            hasError = true;
        }
        
        if (!AuthUtils.validatePassword(password)) {
            AuthUtils.showFieldError('password', '密码至少需要6个字符');
            hasError = true;
        }
        
        if (password !== confirmPassword) {
            AuthUtils.showFieldError('confirmPassword', '两次输入的密码不一致');
            hasError = true;
        }
        
        if (!agreeTerms) {
            AuthUtils.showError('请同意服务条款和隐私政策');
            hasError = true;
        }
        
        if (hasError) return;
        
        // 设置加载状态
        AuthUtils.setButtonLoading('registerButton', true);
        
        try {
            // 发送注册请求
            const response = await AuthAPI.register({
                username: username,
                email: email,
                password: password
            });
            
            // 显示成功消息
            AuthUtils.showSuccess('注册成功！正在跳转到登录页面...');
            
            // 跳转到登录页
            setTimeout(() => {
                window.location.href = 'login.html';
            }, 2000);
            
        } catch (error) {
            AuthUtils.showError(error.message || '注册失败，请稍后重试');
        } finally {
            AuthUtils.setButtonLoading('registerButton', false);
        }
    });
}

// 登出功能
async function logout() {
    try {
        await AuthAPI.logout();
    } catch (error) {
        console.error('登出请求失败:', error);
    } finally {
        // 无论请求是否成功，都清除本地令牌
        AuthUtils.removeToken();
        window.location.href = 'login.html';
    }
}

// 检查认证状态
async function checkAuthStatus() {
    if (!AuthUtils.isLoggedIn()) {
        return null;
    }
    
    try {
        const user = await AuthAPI.getCurrentUser();
        return user;
    } catch (error) {
        // 令牌无效，清除并返回null
        AuthUtils.removeToken();
        return null;
    }
}

// 导出函数供其他模块使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        AuthUtils,
        AuthAPI,
        initLogin,
        initRegister,
        logout,
        checkAuthStatus
    };
}