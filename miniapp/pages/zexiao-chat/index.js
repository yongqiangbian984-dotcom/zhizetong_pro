var config = require('../../config.js');

Page({
  data: {
    messages: [],
    inputValue: '',
    scrollToId: '',
    completion: { total: 0, dimensions: {} },
    sending: false,
    canReport: false,
    focusInput: false,
    statusBarHeight: 44,
    navBarHeight: 88,
    keyboardHeight: 0,
    role: 'student',
    typewriterTimer: null,
    mode: 'chat', // chat=简版聊天, full=6维完整评估
    profile: null,
    reportData: null // 6维报告数据
  },

  onLoad: function(options) {
    var sysInfo = wx.getSystemInfoSync();
    var statusBarHeight = sysInfo.statusBarHeight || 44;
    var navBarHeight = statusBarHeight + 44;
    var isParent = options && options.role === 'parent';
    var mode = (options && options.mode === 'full') ? 'full' : 'chat';

    // 读取profile缓存
    var profile = null;
    try { profile = wx.getStorageSync('zexiao_profile'); } catch(e) {}

    this.setData({
      statusBarHeight: statusBarHeight,
      navBarHeight: navBarHeight,
      role: isParent ? 'parent' : 'student',
      mode: mode,
      profile: profile
    });

    // 如果是完整6维评估模式且有profile，直接调API生成报告
    if (mode === 'full' && profile && profile.province && profile.score) {
      this.callConsultApi(profile);
      return;
    }

    // ── 聊天模式：先读缓存 ──
    var cacheKey = isParent ? 'zexiao_chat_parent' : 'zexiao_chat_student';
    this._cacheKey = cacheKey;
    var cached = null;
    try { cached = wx.getStorageSync(cacheKey); } catch(e) {}

    if (cached && cached.messages && cached.messages.length > 0) {
      this.setData({
        messages: cached.messages,
        completion: cached.completion || { total: 0, dimensions: {} },
        canReport: cached.completion && cached.completion.total >= 90
      });
      this._scrollToLast(400);
      return;
    }

    // ── 没有缓存，显示开场白 ──
    var opening = isParent
      ? '你好，我是智择通。作为家长，你可以告诉我你对孩子的观察和了解，比如孩子平时最愿意花时间做什么？'
      : '你好，我是智择通。咱们先聊聊你平时最愿意花时间做什么？';
    var initMessages = [{ role: 'ai', content: opening }];
    this.setData({ messages: initMessages });
    this._scrollToLast(200);
  },

  onShow: function() {
    this._scrollToLast(300);
  },

  onUnload: function() {
    if (this.data.typewriterTimer) {
      clearInterval(this.data.typewriterTimer);
    }
  },

  // ========== 核心：调用6维API生成报告 ==========
  callConsultApi: function(profile) {
    var that = this;
    var loadingMsg = { role: 'ai', content: '🔄 正在调用6维评估引擎...\n\n⏳ AI正在分析：性格特质 → 家庭资源 → 行业周期 → 地域价值 → 升学竞争 → 容错规划\n\n预计需要30-60秒，请耐心等待...' };
    this.setData({ messages: [loadingMsg], sending: true, canReport: false });
    this._scrollToLast(100);

    var apiBase = config.zexiaoApiBase || 'http://localhost:8080';
    wx.request({
      url: apiBase + '/api/v1/consult',
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: {
        profile: {
          province: profile.province || '',
          score: profile.score || 0,
          subject: profile.subject || '理科',
          target_major: profile.target_major || '',
          target_university: profile.target_university || '',
          family_budget: profile.family_budget || '',
          personality: profile.personality || '',
          career_goal: profile.career_goal || '产业就业'
        }
      },
      timeout: 120000,
      success: function(res) {
        if (res.statusCode === 200 && res.data && res.data.status === 'success') {
          var reportData = res.data.data;
          that.setData({ reportData: reportData, canReport: true, sending: false });
          // 格式化报告为聊天消息
          var reportText = that.formatReport(reportData);
          that.setData({
            messages: [{ role: 'ai', content: reportText }],
            completion: { total: 100, dimensions: { personality: 100, fri: 100, kondratiev: 100, location: 100, competition: 100, contingency: 100 } }
          });
          that._scrollToLast(200);
          // 缓存
          try {
            wx.setStorageSync(that._cacheKey || 'zexiao_chat_student', {
              messages: that.data.messages,
              completion: that.data.completion
            });
          } catch(e) {}
          // 提示生成报告
          setTimeout(function() {
            wx.showModal({
              title: '6维评估完成 ✦',
              content: '报告已生成，可以查看完整的择校分析报告了！',
              confirmText: '查看报告',
              cancelText: '继续聊',
              success: function(modalRes) {
                if (modalRes.confirm) {
                  that.goToReport();
                }
              }
            });
          }, 500);
        } else {
          var errMsg = '评估失败';
          if (res.data && res.data.message) errMsg = res.data.message;
          if (res.data && res.data.raw_content) errMsg = 'AI返回格式异常，请重试';
          that.setData({
            messages: [{ role: 'ai', content: '❌ ' + errMsg + '\n\n请返回重试，或切换到聊天模式。' }],
            sending: false
          });
        }
      },
      fail: function(err) {
        that.setData({
          messages: [{ role: 'ai', content: '❌ 网络请求失败，请检查：\n1. Docker后端是否在运行\n2. 手机和电脑在同一网络\n3. API地址是否正确\n\n当前地址：' + apiBase }],
          sending: false
        });
      }
    });
  },

  // ========== 格式化6维报告为可读文本 ==========
  formatReport: function(data) {
    var text = '📋 【智择通6维择校评估报告】\n\n';

    if (data.step1_personality) {
      var p = data.step1_personality;
      text += '🧠 一、性格特质分析\n';
      text += '决策风格：' + (p.decision_style || '-') + '\n';
      text += '兴趣深度：' + (p.interest_depth || '-') + '\n';
      text += '依据：' + (p.evidence || '-') + '\n\n';
    }

    if (data.step2_fri) {
      var f = data.step2_fri;
      text += '💰 二、家庭资源评估(FRI)\n';
      text += 'FRI指数：' + (f.fri_index || '-') + '\n';
      text += '资源层级：' + (f.resource_level || '-') + '\n';
      text += '承接能力：' + (f.carrying_capacity || '-') + '\n\n';
    }

    if (data.step3_kondratiev) {
      var k = data.step3_kondratiev;
      text += '📈 三、行业周期研判\n';
      text += '行业阶段：' + (k.industry_phase || '-') + '\n';
      text += 'AI替代风险：' + (k.ai_risk || '-') + '\n';
      text += '趋势建议：' + (k.trend_advice || '-') + '\n\n';
    }

    if (data.step4_location) {
      var l = data.step4_location;
      text += '🏙️ 四、地域价值核算\n';
      text += '城市层级：' + (l.city_tier || '-') + '\n';
      text += '时间价值：' + (l.time_value || '-') + '\n';
      text += '策略：' + (l.strategy || '-') + '\n\n';
    }

    if (data.step5_competition) {
      var c = data.step5_competition;
      text += '🎓 五、升学竞争评估\n';
      text += '难度：' + (c.difficulty || '-') + '\n';
      text += 'ROI：' + (c.roi || '-') + '\n';
      text += '位次分析：' + (c.rank_analysis || '-') + '\n\n';
    }

    if (data.step6_contingency) {
      var s = data.step6_contingency;
      text += '🎯 六、容错规划\n';
      if (s.Plan_A) text += '【Plan A 冲刺】' + (typeof s.Plan_A === 'string' ? s.Plan_A : JSON.stringify(s.Plan_A)) + '\n\n';
      if (s.Plan_B) text += '【Plan B 稳妥】' + (typeof s.Plan_B === 'string' ? s.Plan_B : JSON.stringify(s.Plan_B)) + '\n\n';
      if (s.Plan_C) text += '【Plan C 保底】' + (typeof s.Plan_C === 'string' ? s.Plan_C : JSON.stringify(s.Plan_C)) + '\n\n';
    }

    if (data.risk_warning) {
      text += '⚠️ 风险提示：' + data.risk_warning + '\n';
    }

    return text;
  },

  // ========== 聊天模式发送消息 ==========
  onInput: function(e) {
    this.setData({ inputValue: e.detail.value });
  },

  onInputBlur: function() {
    this.setData({ focusInput: false, keyboardHeight: 0 });
  },

  onKeyboardChange: function(e) {
    var h = e.detail ? e.detail.height : 0;
    this.setData({ keyboardHeight: h });
    if (h > 0) {
      this._scrollToLast(250);
    }
  },

  goBack: function() {
    wx.navigateBack();
  },

  goToReport: function() {
    // 如果有6维报告数据，存缓存
    if (this.data.reportData) {
      try { wx.setStorageSync('zexiao_report_data', this.data.reportData); } catch(e) {}
    }
    wx.navigateTo({ url: '/pages/zexiao-report/index?mode=full' });
  },

  sendMessage: function() {
    if (!this.data.inputValue || this.data.sending) return;
    var msg = this.data.inputValue.trim();
    if (!msg) return;

    var userMsg = { role: 'user', content: msg };
    var newMessages = this.data.messages.concat([userMsg]);
    this.setData({
      messages: newMessages,
      inputValue: '',
      sending: true,
      focusInput: true
    });
    this._scrollToLast(100);

    var that = this;
    var apiBase = config.zexiaoApiBase || 'http://localhost:8080';
    var history = this.data.messages.slice(-10).map(function(m) {
      return { role: m.role === 'user' ? 'user' : 'assistant', content: m.content };
    });

    wx.request({
      url: apiBase + '/api/v1/chat',
      method: 'POST',
      header: { 'content-type': 'application/json' },
      data: { message: msg, history: history, role: that.data.role },
      timeout: 60000,
      success: function(res) {
        if (res.statusCode === 200 && res.data && res.data.code === 0) {
          var data = res.data.data;
          var aiContent = data.reply || '抱歉，我暂时无法回复';
          var canReport = data.canReport || false;

          var allMessages = that.data.messages.concat([{ role: 'ai', content: '' }]);
          that.setData({
            messages: allMessages,
            canReport: canReport,
            sending: false
          });
          that._scrollToLast(100);
          that.startTypewriter(aiContent, that.data.completion);

          if (canReport) {
            setTimeout(function() {
              wx.showModal({
                title: '评估完成 ✦',
                content: '信息已收集完成，可以生成你的专属择校报告了！',
                confirmText: '生成报告',
                cancelText: '再聊聊',
                success: function(modalRes) {
                  if (modalRes.confirm) {
                    var profile = that.data.profile || {};
                    profile.personality = msg;
                    that.callConsultApi(profile);
                  }
                }
              });
            }, 1000);
          }
        } else {
          var errMsg = '抱歉，出了点问题';
          if (res.data && res.data.detail) errMsg = res.data.detail;
          that.setData({
            messages: that.data.messages.concat([{ role: 'ai', content: '❌ ' + errMsg }]),
            sending: false
          });
        }
      },
      fail: function() {
        that.setData({
          messages: that.data.messages.concat([{ role: 'ai', content: '❌ 网络请求失败，请检查Docker后端是否在运行\n当前地址：' + apiBase }]),
          sending: false
        });
      }
    });
  },

  // ========== 打字机效果 ==========
  startTypewriter: function(text, completion) {
    var that = this;
    var idx = 0;
    var currentContent = '';
    var timer = setInterval(function() {
      if (idx >= text.length) {
        clearInterval(timer);
        that.setData({ typewriterTimer: null });
        var finalMessages = that.data.messages;
        finalMessages[finalMessages.length - 1] = { role: 'ai', content: text };
        that.setData({ messages: finalMessages, completion: completion });
        that._saveCache(finalMessages, completion);
        return;
      }
      currentContent += text[idx];
      idx++;
      var msgs = that.data.messages;
      msgs[msgs.length - 1] = { role: 'ai', content: currentContent };
      that.setData({ messages: msgs });
      if (idx % 5 === 0) that._scrollToLast(50);
    }, 30);
    that.setData({ typewriterTimer: timer });
  },

  _scrollToLast: function(delay) {
    var that = this;
    setTimeout(function() {
      that.setData({ scrollToId: 'msg-bottom' });
    }, delay || 200);
  },

  _saveCache: function(messages, completion) {
    try {
      wx.setStorageSync(this._cacheKey || 'zexiao_chat_student', {
        messages: messages,
        completion: completion
      });
    } catch(e) {}
  }
});
