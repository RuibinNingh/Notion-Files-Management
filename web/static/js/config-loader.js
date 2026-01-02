document.addEventListener('DOMContentLoaded', () => {
    fetch('config.yaml')
        .then(response => response.text())
        .then(yamlText => {
            const config = jsyaml.load(yamlText);
            renderSite(config);
        })
        .catch(error => console.error('Error loading config:', error));
});

function getDataAttribute(element) {
    if (!element) return '';
    const attr = Array.from(element.attributes).find(a => a.name.startsWith('data-v-'));
    return attr ? ` ${attr.name}="${attr.value}"` : '';
}

function renderSite(config) {
    // 1. Site Meta
    if (config.site) {
        document.title = config.site.title;
        const descMeta = document.querySelector('meta[name="description"]');
        if (descMeta) descMeta.content = config.site.description;
    }

    // 2. Navigation
    if (config.navigation) {
        renderNavigation(config.navigation);
    }

    // 3. Hero Section
    if (config.hero) {
        renderHero(config.hero);
    }

    // 4. Deployment Section
    if (config.deployment) {
        renderDeployment(config.deployment);
    }

    // 5. Footer
    if (config.footer) {
        renderFooter(config.footer);
    }
}

function renderNavigation(navConfig) {
    // Logo
    if (navConfig.logo) {
        const logoImg = document.querySelector('.header .logo');
        const logoText = document.querySelector('.header .name');
        if (logoImg) {
            logoImg.src = navConfig.logo.image;
            logoImg.alt = navConfig.logo.alt;
        }
        if (logoText) logoText.textContent = navConfig.logo.text;
    }

    // Nav Items
    if (navConfig.items) {
        const navContainer = document.querySelector('.header .nav');
        if (navContainer) {
            const dataAttr = getDataAttribute(navContainer);
            navContainer.innerHTML = ''; // Clear existing
            navConfig.items.forEach(item => {
                const a = document.createElement('a');
                a.href = item.link || '';
                a.className = 'link';
                a.textContent = item.text;
                if (item.target) a.target = item.target;
                if (item.active) a.classList.add('router-link-active');
                
                // Apply data attribute
                if (dataAttr) {
                    const [name, value] = dataAttr.trim().split('=');
                    a.setAttribute(name, value.replace(/"/g, ''));
                }
                
                navContainer.appendChild(a);
            });
        }
    }
}

function renderHero(heroConfig) {
    const heroSection = document.querySelector('.hero');
    if (!heroSection) return;

    // Title
    const titleEl = heroSection.querySelector('.title');
    if (titleEl) {
        const prefix = heroConfig.title_prefix || '';
        const suffix = heroConfig.title_suffix || '';
        
        // Preserve structure for typewriter
        const dataAttr = getDataAttribute(titleEl);
        // Extract just the attribute string for innerHTML usage
        
        titleEl.innerHTML = ` ${prefix} <span class="typewriter-text"${dataAttr}></span><span class="blink cursor"${dataAttr}>|</span> ${suffix} `;
        
        // Handle Highlight Text vs Typewriter
        if (heroConfig.highlight_text) {
             const typeWriterSpan = titleEl.querySelector('.typewriter-text');
             if (typeWriterSpan) typeWriterSpan.textContent = heroConfig.highlight_text;
             const cursor = titleEl.querySelector('.cursor');
             if (cursor) cursor.style.display = 'none';
        } else if (heroConfig.typewriter_texts) {
            initTypewriter(heroConfig.typewriter_texts);
        }
    }

    // Description
    const descEl = heroSection.querySelector('.desc');
    if (descEl) descEl.textContent = heroConfig.description;

    // Buttons
    if (heroConfig.buttons) {
        const actionsEl = heroSection.querySelector('.actions');
        if (actionsEl) {
            const dataAttr = getDataAttribute(actionsEl);
            actionsEl.innerHTML = '';
            heroConfig.buttons.forEach(btn => {
                const a = document.createElement('a');
                a.href = btn.link;
                a.className = `btn ${btn.class}`;
                a.textContent = btn.text;
                if (btn.target) a.target = btn.target;
                
                if (dataAttr) {
                    const [name, value] = dataAttr.trim().split('=');
                    a.setAttribute(name, value.replace(/"/g, ''));
                }
                
                actionsEl.appendChild(a);
            });
        }
    }
}

function initTypewriter(texts) {
    const textElement = document.querySelector('.typewriter-text');
    if (!textElement || !texts || texts.length === 0) return;

    let wordIndex = 0;
    let charIndex = 0;
    let isDeleting = false;

    function type() {
        const currentWord = texts[wordIndex];
        
        if (isDeleting) {
            textElement.textContent = currentWord.substring(0, charIndex - 1);
            charIndex--;
        } else {
            textElement.textContent = currentWord.substring(0, charIndex + 1);
            charIndex++;
        }
        
        let typeSpeed = isDeleting ? 100 : 200;
        
        if (!isDeleting && charIndex === currentWord.length) {
            isDeleting = true;
            typeSpeed = 2000;
        } else if (isDeleting && charIndex === 0) {
            isDeleting = false;
            wordIndex = (wordIndex + 1) % texts.length;
            typeSpeed = 500;
        }
        
        setTimeout(type, typeSpeed);
    }
    
    type();
}

function renderDeployment(deployConfig) {
    const section = document.querySelector('.deployment-section');
    if (!section) return;

    // Header
    const titleEl = section.querySelector('.header .title');
    if (titleEl) titleEl.textContent = deployConfig.title;
    const subtitleEl = section.querySelector('.header .subtitle');
    if (subtitleEl) subtitleEl.textContent = deployConfig.subtitle;

    // Tabs
    const tabsContainer = section.querySelector('.deployment-tabs');
    const contentContainer = section.querySelector('.deployment-content');
    
    if (tabsContainer && deployConfig.tabs) {
        const dataAttr = getDataAttribute(tabsContainer);
        tabsContainer.innerHTML = '';
        
        // Create Tabs
        deployConfig.tabs.forEach((tab, index) => {
            const tabEl = document.createElement('div');
            tabEl.className = `deployment-tab ${index === 0 ? 'active' : ''}`;
            tabEl.setAttribute('data-tab', tab.id);
            tabEl.onclick = () => switchDeploymentTab(tab.id, deployConfig.tabs);
            
            if (dataAttr) {
                const [name, value] = dataAttr.trim().split('=');
                tabEl.setAttribute(name, value.replace(/"/g, ''));
            }

            let iconHtml = '';
            if (tab.icon_path) {
                iconHtml = `<svg fill="currentColor" class="icon"${dataAttr} viewBox="${tab.viewBox || '0 0 1024 1024'}" width="24" height="24"><path d="${tab.icon_path}"${dataAttr}></path></svg>`;
            } else if (tab.icon_svg) {
                // Should inject dataAttr into svg if possible, but simple replacement works
                iconHtml = tab.icon_svg.replace('<svg', `<svg${dataAttr}`);
            }

            tabEl.innerHTML = `
                <div class="tab-icon"${dataAttr}>${iconHtml}</div>
                <span${dataAttr}>${tab.name}</span>
            `;
            tabsContainer.appendChild(tabEl);
        });

        // Initial Content Render
        renderDeploymentContent(deployConfig.tabs[0], contentContainer);
    }
}

function switchDeploymentTab(tabId, tabs) {
    // Update active tab
    document.querySelectorAll('.deployment-tab').forEach(tab => {
        if (tab.getAttribute('data-tab') === tabId) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    // Update Content
    const tabData = tabs.find(t => t.id === tabId);
    const contentContainer = document.querySelector('.deployment-content');
    if (tabData && contentContainer) {
        renderDeploymentContent(tabData, contentContainer);
    }
}

function formatText(text) {
    if (!text) return '';
    // Replace {{text}} with blue span
    return text.replace(/\{\{(.*?)\}\}/g, '<span style="color: #3579f6">$1</span>');
}

function renderDeploymentContent(tabData, container) {
    const content = tabData.content;
    const dataAttr = getDataAttribute(container);
    
    // Stars
    const starsHtml = Array(5).fill(0).map((_, i) => 
        `<span class="${i < content.info.difficulty ? 'filled' : ''} star"${dataAttr}> ★ </span>`
    ).join('');

    // Advantages
    const advantagesHtml = content.advantages.map(adv => `
        <div class="advantage-item"${dataAttr}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"${dataAttr}>
                <polyline points="20,6 9,17 4,12"${dataAttr}></polyline>
            </svg> 
            ${formatText(adv.text)}
        </div>
    `).join('');

    // Considerations
    const considerationsHtml = content.considerations ? content.considerations.map(item => `
        <div class="consideration-item"${dataAttr}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"${dataAttr}>
                <path d="m21 21-6-6m6 6v-4.8m0 4.8h-4.8"${dataAttr}></path>
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"${dataAttr}></path>
            </svg> 
            ${formatText(item.text)}
        </div>
    `).join('') : '';

    // Steps
    const stepsHtml = content.steps.map(step => `
        <div class="step-item"${dataAttr}>
            <div class="step-number"${dataAttr}>${step.number}</div>
            <div class="step-content"${dataAttr}>
                <h5${dataAttr}>${formatText(step.title)}</h5>
                <p${dataAttr}>${formatText(step.desc || '')}</p>
                <div class="step-code"${dataAttr}>
                    <pre${dataAttr}><code${dataAttr}>${step.code}</code></pre>
                    <button class="copy-btn" onclick="copyCode(this)"${dataAttr}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"${dataAttr}>
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"${dataAttr}></rect>
                            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"${dataAttr}></path>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `).join('');

    // Buttons
    let buttonsHtml = '';
    if (content.buttons) {
        if (content.buttons.primary) {
            buttonsHtml += `<a href="${content.buttons.primary.link}" class="btn primary"${dataAttr}>${content.buttons.primary.text}</a>`;
        }
        if (content.buttons.secondary) {
            buttonsHtml += `<a href="${content.buttons.secondary.link}" class="btn ghost"${dataAttr}>${content.buttons.secondary.text}</a>`;
        }
    } else {
        buttonsHtml = `<button class="btn primary"${dataAttr}>开始部署</button><button class="btn ghost"${dataAttr}>查看文档</button>`;
    }

    const html = `
        <div class="deployment-card"${dataAttr}>
            <div class="card-header"${dataAttr}>
                ${content.recommended ? `<div class="recommended card-badge"${dataAttr}>推荐</div>` : ''}
                <h3${dataAttr}>${formatText(content.title)}</h3>
                <p class="card-description"${dataAttr}>${formatText(content.description)}</p>
            </div>
            <div class="card-body"${dataAttr}>
                <div class="deployment-info"${dataAttr}>
                    <div class="info-grid"${dataAttr}>
                        <div class="info-item"${dataAttr}>
                            <div class="info-label"${dataAttr}>难度等级</div>
                            <div class="difficulty-stars"${dataAttr}>${starsHtml}</div>
                        </div>
                        <div class="info-item"${dataAttr}>
                            <div class="info-label"${dataAttr}>启动时间</div>
                            <div class="info-value"${dataAttr}>${content.info.startup_time}</div>
                        </div>
                        <div class="info-item"${dataAttr}>
                            <div class="info-label"${dataAttr}>维护成本</div>
                            <div class="info-value"${dataAttr}>${content.info.maintenance}</div>
                        </div>
                        <div class="info-item"${dataAttr}>
                            <div class="info-label"${dataAttr}>适用场景</div>
                            <div class="info-value"${dataAttr}>${formatText(content.info.scenario)}</div>
                        </div>
                    </div>
                    <div class="advantages"${dataAttr}>
                        <h4${dataAttr}>优势特点</h4>
                        <div class="advantage-list"${dataAttr}>${advantagesHtml}</div>
                    </div>
                    ${considerationsHtml ? `
                    <div class="considerations"${dataAttr}>
                        <h4${dataAttr}>注意事项</h4>
                        <div class="consideration-list"${dataAttr}>${considerationsHtml}</div>
                    </div>` : ''}
                </div>
                <div class="deployment-steps"${dataAttr}>
                    <h4${dataAttr}>快速开始</h4>
                    <div class="steps-container"${dataAttr}>${stepsHtml}</div>
                </div>
            </div>
            <div class="card-footer"${dataAttr}>${buttonsHtml}</div>
        </div>
    `;

    container.innerHTML = html;
}

function renderFooter(footerConfig) {
    const footer = document.querySelector('.footer');
    if (!footer) return;

    const copyright = footer.querySelector('.copyright');
    if (copyright) copyright.textContent = footerConfig.copyright;

    const icpLink = footer.querySelector('.beian-link');
    if (icpLink) {
        icpLink.textContent = ` ${footerConfig.icp} `;
        if (footerConfig.icp_link) icpLink.href = footerConfig.icp_link;
    }
}

function copyCode(btn) {
    const code = btn.previousElementSibling.textContent;
    navigator.clipboard.writeText(code).then(() => {
        const originalIcon = btn.innerHTML;
        btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="green" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
        setTimeout(() => {
            btn.innerHTML = originalIcon;
        }, 2000);
    });
}
