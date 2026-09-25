var Yf = { exports: {} }, at = {};
var Mh;
function Jv() {
  if (Mh) return at;
  Mh = 1;
  var c = /* @__PURE__ */ Symbol.for("react.transitional.element"), r = /* @__PURE__ */ Symbol.for("react.portal"), y = /* @__PURE__ */ Symbol.for("react.fragment"), o = /* @__PURE__ */ Symbol.for("react.strict_mode"), h = /* @__PURE__ */ Symbol.for("react.profiler"), D = /* @__PURE__ */ Symbol.for("react.consumer"), R = /* @__PURE__ */ Symbol.for("react.context"), p = /* @__PURE__ */ Symbol.for("react.forward_ref"), q = /* @__PURE__ */ Symbol.for("react.suspense"), M = /* @__PURE__ */ Symbol.for("react.memo"), z = /* @__PURE__ */ Symbol.for("react.lazy"), N = /* @__PURE__ */ Symbol.for("react.activity"), w = /* @__PURE__ */ Symbol.for("react.view_transition"), Y = Symbol.iterator;
  function F(d) {
    return d === null || typeof d != "object" ? null : (d = Y && d[Y] || d["@@iterator"], typeof d == "function" ? d : null);
  }
  var B = {
    isMounted: function() {
      return !1;
    },
    enqueueForceUpdate: function() {
    },
    enqueueReplaceState: function() {
    },
    enqueueSetState: function() {
    }
  }, Q = Object.assign, rt = {};
  function nt(d, E, _) {
    this.props = d, this.context = E, this.refs = rt, this.updater = _ || B;
  }
  nt.prototype.isReactComponent = {}, nt.prototype.setState = function(d, E) {
    if (typeof d != "object" && typeof d != "function" && d != null)
      throw Error(
        "takes an object of state variables to update or a function which returns an object of state variables."
      );
    this.updater.enqueueSetState(this, d, E, "setState");
  }, nt.prototype.forceUpdate = function(d) {
    this.updater.enqueueForceUpdate(this, d, "forceUpdate");
  };
  function wt() {
  }
  wt.prototype = nt.prototype;
  function bt(d, E, _) {
    this.props = d, this.context = E, this.refs = rt, this.updater = _ || B;
  }
  var ft = bt.prototype = new wt();
  ft.constructor = bt, Q(ft, nt.prototype), ft.isPureReactComponent = !0;
  var dt = Array.isArray;
  function V() {
  }
  var k = { H: null, A: null, T: null, S: null }, qt = Object.prototype.hasOwnProperty;
  function xt(d, E, _) {
    var U = _.ref;
    return {
      $$typeof: c,
      type: d,
      key: E,
      ref: U !== void 0 ? U : null,
      props: _
    };
  }
  function Yt(d, E) {
    return xt(d.type, E, d.props);
  }
  function Lt(d) {
    return typeof d == "object" && d !== null && d.$$typeof === c;
  }
  function Ht(d) {
    var E = { "=": "=0", ":": "=2" };
    return "$" + d.replace(/[=:]/g, function(_) {
      return E[_];
    });
  }
  var $t = /\/+/g;
  function Rt(d, E) {
    return typeof d == "object" && d !== null && d.key != null ? Ht("" + d.key) : E.toString(36);
  }
  function X(d) {
    switch (d.status) {
      case "fulfilled":
        return d.value;
      case "rejected":
        throw d.reason;
      default:
        switch (typeof d.status == "string" ? d.then(V, V) : (d.status = "pending", d.then(
          function(E) {
            d.status === "pending" && (d.status = "fulfilled", d.value = E);
          },
          function(E) {
            d.status === "pending" && (d.status = "rejected", d.reason = E);
          }
        )), d.status) {
          case "fulfilled":
            return d.value;
          case "rejected":
            throw d.reason;
        }
    }
    throw d;
  }
  function P(d, E, _, U, H) {
    var K = typeof d;
    (K === "undefined" || K === "boolean") && (d = null);
    var et = !1;
    if (d === null) et = !0;
    else
      switch (K) {
        case "bigint":
        case "string":
        case "number":
          et = !0;
          break;
        case "object":
          switch (d.$$typeof) {
            case c:
            case r:
              et = !0;
              break;
            case z:
              return et = d._init, P(
                et(d._payload),
                E,
                _,
                U,
                H
              );
          }
      }
    if (et)
      return H = H(d), et = U === "" ? "." + Rt(d, 0) : U, dt(H) ? (_ = "", et != null && (_ = et.replace($t, "$&/") + "/"), P(H, E, _, "", function(Dt) {
        return Dt;
      })) : H != null && (Lt(H) && (H = Yt(
        H,
        _ + (H.key == null || d && d.key === H.key ? "" : ("" + H.key).replace(
          $t,
          "$&/"
        ) + "/") + et
      )), E.push(H)), 1;
    et = 0;
    var G = U === "" ? "." : U + ":";
    if (dt(d))
      for (var W = 0; W < d.length; W++)
        U = d[W], K = G + Rt(U, W), et += P(
          U,
          E,
          _,
          K,
          H
        );
    else if (W = F(d), typeof W == "function")
      for (d = W.call(d), W = 0; !(U = d.next()).done; )
        U = U.value, K = G + Rt(U, W++), et += P(
          U,
          E,
          _,
          K,
          H
        );
    else if (K === "object") {
      if (typeof d.then == "function")
        return P(
          X(d),
          E,
          _,
          U,
          H
        );
      throw E = String(d), Error(
        "Objects are not valid as a React child (found: " + (E === "[object Object]" ? "object with keys {" + Object.keys(d).join(", ") + "}" : E) + "). If you meant to render a collection of children, use an array instead."
      );
    }
    return et;
  }
  function I(d, E, _) {
    if (d == null) return d;
    var U = [], H = 0;
    return P(d, U, "", "", function(K) {
      return E.call(_, K, H++);
    }), U;
  }
  function pt(d) {
    if (d._status === -1) {
      var E = d._result, _ = E();
      _.then(
        function(U) {
          (d._status === 0 || d._status === -1) && (d._status = 1, d._result = U, _.status === void 0 && (_.status = "fulfilled", _.value = U));
        },
        function(U) {
          (d._status === 0 || d._status === -1) && (d._status = 2, d._result = U, _.status === void 0 && (_.status = "rejected", _.reason = U));
        }
      ), d._status === -1 && (d._status = 0, d._result = _);
    }
    if (d._status === 1) return d._result.default;
    throw d._result;
  }
  var st = typeof reportError == "function" ? reportError : function(d) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var E = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof d == "object" && d !== null && typeof d.message == "string" ? String(d.message) : String(d),
        error: d
      });
      if (!window.dispatchEvent(E)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", d);
      return;
    }
    console.error(d);
  };
  function ee(d) {
    var E = k.T, _ = {};
    _.types = E !== null ? E.types : null, k.T = _;
    try {
      var U = d(), H = k.S;
      H !== null && H(_, U), typeof U == "object" && U !== null && typeof U.then == "function" && U.then(V, st);
    } catch (K) {
      st(K);
    } finally {
      E !== null && _.types !== null && (E.types = _.types), k.T = E;
    }
  }
  function Se(d) {
    var E = k.T;
    if (E !== null) {
      var _ = E.types;
      _ === null ? E.types = [d] : _.indexOf(d) === -1 && _.push(d);
    } else ee(Se.bind(null, d));
  }
  var A = {
    map: I,
    forEach: function(d, E, _) {
      I(
        d,
        function() {
          E.apply(this, arguments);
        },
        _
      );
    },
    count: function(d) {
      var E = 0;
      return I(d, function() {
        E++;
      }), E;
    },
    toArray: function(d) {
      return I(d, function(E) {
        return E;
      }) || [];
    },
    only: function(d) {
      if (!Lt(d))
        throw Error(
          "React.Children.only expected to receive a single React element child."
        );
      return d;
    }
  };
  return at.Activity = N, at.Children = A, at.Component = nt, at.Fragment = y, at.Profiler = h, at.PureComponent = bt, at.StrictMode = o, at.Suspense = q, at.ViewTransition = w, at.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = k, at.__COMPILER_RUNTIME = {
    __proto__: null,
    c: function(d) {
      return k.H.useMemoCache(d);
    }
  }, at.addTransitionType = Se, at.cache = function(d) {
    return function() {
      return d.apply(null, arguments);
    };
  }, at.cacheSignal = function() {
    return null;
  }, at.cloneElement = function(d, E, _) {
    if (d == null)
      throw Error(
        "The argument must be a React element, but you passed " + d + "."
      );
    var U = Q({}, d.props), H = d.key;
    if (E != null)
      for (K in E.key !== void 0 && (H = "" + E.key), E)
        !qt.call(E, K) || K === "key" || K === "__self" || K === "__source" || K === "ref" && E.ref === void 0 || (U[K] = E[K]);
    var K = arguments.length - 2;
    if (K === 1) U.children = _;
    else if (1 < K) {
      for (var et = Array(K), G = 0; G < K; G++)
        et[G] = arguments[G + 2];
      U.children = et;
    }
    return xt(d.type, H, U);
  }, at.createContext = function(d) {
    return d = {
      $$typeof: R,
      _currentValue: d,
      _currentValue2: d,
      _threadCount: 0,
      Provider: null,
      Consumer: null
    }, d.Provider = d, d.Consumer = {
      $$typeof: D,
      _context: d
    }, d;
  }, at.createElement = function(d, E, _) {
    var U, H = {}, K = null;
    if (E != null)
      for (U in E.key !== void 0 && (K = "" + E.key), E)
        qt.call(E, U) && U !== "key" && U !== "__self" && U !== "__source" && (H[U] = E[U]);
    var et = arguments.length - 2;
    if (et === 1) H.children = _;
    else if (1 < et) {
      for (var G = Array(et), W = 0; W < et; W++)
        G[W] = arguments[W + 2];
      H.children = G;
    }
    if (d && d.defaultProps)
      for (U in et = d.defaultProps, et)
        H[U] === void 0 && (H[U] = et[U]);
    return xt(d, K, H);
  }, at.createRef = function() {
    return { current: null };
  }, at.forwardRef = function(d) {
    return { $$typeof: p, render: d };
  }, at.isValidElement = Lt, at.lazy = function(d) {
    return {
      $$typeof: z,
      _payload: { _status: -1, _result: d },
      _init: pt
    };
  }, at.memo = function(d, E) {
    return {
      $$typeof: M,
      type: d,
      compare: E === void 0 ? null : E
    };
  }, at.startTransition = ee, at.unstable_useCacheRefresh = function() {
    return k.H.useCacheRefresh();
  }, at.use = function(d) {
    return k.H.use(d);
  }, at.useActionState = function(d, E, _) {
    return k.H.useActionState(d, E, _);
  }, at.useCallback = function(d, E) {
    return k.H.useCallback(d, E);
  }, at.useContext = function(d) {
    return k.H.useContext(d);
  }, at.useDebugValue = function() {
  }, at.useDeferredValue = function(d, E) {
    return k.H.useDeferredValue(d, E);
  }, at.useEffect = function(d, E) {
    return k.H.useEffect(d, E);
  }, at.useEffectEvent = function(d) {
    return k.H.useEffectEvent(d);
  }, at.useId = function() {
    return k.H.useId();
  }, at.useImperativeHandle = function(d, E, _) {
    return k.H.useImperativeHandle(d, E, _);
  }, at.useInsertionEffect = function(d, E) {
    return k.H.useInsertionEffect(d, E);
  }, at.useLayoutEffect = function(d, E) {
    return k.H.useLayoutEffect(d, E);
  }, at.useMemo = function(d, E) {
    return k.H.useMemo(d, E);
  }, at.useOptimistic = function(d, E) {
    return k.H.useOptimistic(d, E);
  }, at.useReducer = function(d, E, _) {
    return k.H.useReducer(d, E, _);
  }, at.useRef = function(d) {
    return k.H.useRef(d);
  }, at.useState = function(d) {
    return k.H.useState(d);
  }, at.useSyncExternalStore = function(d, E, _) {
    return k.H.useSyncExternalStore(
      d,
      E,
      _
    );
  }, at.useTransition = function() {
    return k.H.useTransition();
  }, at.version = "19.3.0", at;
}
var Ch;
function Pf() {
  return Ch || (Ch = 1, Yf.exports = Jv()), Yf.exports;
}
var J = Pf(), Lf = { exports: {} }, gu = {}, Xf = { exports: {} }, Gf = {};
var Rh;
function $v() {
  return Rh || (Rh = 1, (function(c) {
    function r(X, P) {
      var I = X.length;
      X.push(P);
      t: for (; 0 < I; ) {
        var pt = I - 1 >>> 1, st = X[pt];
        if (0 < h(st, P))
          X[pt] = P, X[I] = st, I = pt;
        else break t;
      }
    }
    function y(X) {
      return X.length === 0 ? null : X[0];
    }
    function o(X) {
      if (X.length === 0) return null;
      var P = X[0], I = X.pop();
      if (I !== P) {
        X[0] = I;
        t: for (var pt = 0, st = X.length, ee = st >>> 1; pt < ee; ) {
          var Se = 2 * (pt + 1) - 1, A = X[Se], d = Se + 1, E = X[d];
          if (0 > h(A, I))
            d < st && 0 > h(E, A) ? (X[pt] = E, X[d] = I, pt = d) : (X[pt] = A, X[Se] = I, pt = Se);
          else if (d < st && 0 > h(E, I))
            X[pt] = E, X[d] = I, pt = d;
          else break t;
        }
      }
      return P;
    }
    function h(X, P) {
      var I = X.sortIndex - P.sortIndex;
      return I !== 0 ? I : X.id - P.id;
    }
    if (c.unstable_now = void 0, typeof performance == "object" && typeof performance.now == "function") {
      var D = performance;
      c.unstable_now = function() {
        return D.now();
      };
    } else {
      var R = Date, p = R.now();
      c.unstable_now = function() {
        return R.now() - p;
      };
    }
    var q = [], M = [], z = 1, N = null, w = 3, Y = !1, F = !1, B = !1, Q = !1, rt = typeof setTimeout == "function" ? setTimeout : null, nt = typeof clearTimeout == "function" ? clearTimeout : null, wt = typeof setImmediate < "u" ? setImmediate : null;
    function bt(X) {
      for (var P = y(M); P !== null; ) {
        if (P.callback === null) o(M);
        else if (P.startTime <= X)
          o(M), P.sortIndex = P.expirationTime, r(q, P);
        else break;
        P = y(M);
      }
    }
    function ft(X) {
      if (B = !1, bt(X), !F)
        if (y(q) !== null)
          F = !0, dt || (dt = !0, Lt());
        else {
          var P = y(M);
          P !== null && Rt(ft, P.startTime - X);
        }
    }
    var dt = !1, V = -1, k = 5, qt = -1;
    function xt() {
      return Q ? !0 : !(c.unstable_now() - qt < k);
    }
    function Yt() {
      if (Q = !1, dt) {
        var X = c.unstable_now();
        qt = X;
        var P = !0;
        try {
          t: {
            F = !1, B && (B = !1, nt(V), V = -1), Y = !0;
            var I = w;
            try {
              e: {
                for (bt(X), N = y(q); N !== null && !(N.expirationTime > X && xt()); ) {
                  var pt = N.callback;
                  if (typeof pt == "function") {
                    N.callback = null, w = N.priorityLevel;
                    var st = pt(
                      N.expirationTime <= X
                    );
                    if (X = c.unstable_now(), typeof st == "function") {
                      N.callback = st, bt(X), P = !0;
                      break e;
                    }
                    N === y(q) && o(q), bt(X);
                  } else o(q);
                  N = y(q);
                }
                if (N !== null) P = !0;
                else {
                  var ee = y(M);
                  ee !== null && Rt(
                    ft,
                    ee.startTime - X
                  ), P = !1;
                }
              }
              break t;
            } finally {
              N = null, w = I, Y = !1;
            }
            P = void 0;
          }
        } finally {
          P ? Lt() : dt = !1;
        }
      }
    }
    var Lt;
    if (typeof wt == "function")
      Lt = function() {
        wt(Yt);
      };
    else if (typeof MessageChannel < "u") {
      var Ht = new MessageChannel(), $t = Ht.port2;
      Ht.port1.onmessage = Yt, Lt = function() {
        $t.postMessage(null);
      };
    } else
      Lt = function() {
        rt(Yt, 0);
      };
    function Rt(X, P) {
      V = rt(function() {
        X(c.unstable_now());
      }, P);
    }
    c.unstable_IdlePriority = 5, c.unstable_ImmediatePriority = 1, c.unstable_LowPriority = 4, c.unstable_NormalPriority = 3, c.unstable_Profiling = null, c.unstable_UserBlockingPriority = 2, c.unstable_cancelCallback = function(X) {
      X.callback = null;
    }, c.unstable_forceFrameRate = function(X) {
      0 > X || 125 < X ? console.error(
        "forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported"
      ) : k = 0 < X ? Math.floor(1e3 / X) : 5;
    }, c.unstable_getCurrentPriorityLevel = function() {
      return w;
    }, c.unstable_next = function(X) {
      switch (w) {
        case 1:
        case 2:
        case 3:
          var P = 3;
          break;
        default:
          P = w;
      }
      var I = w;
      w = P;
      try {
        return X();
      } finally {
        w = I;
      }
    }, c.unstable_requestPaint = function() {
      Q = !0;
    }, c.unstable_runWithPriority = function(X, P) {
      switch (X) {
        case 1:
        case 2:
        case 3:
        case 4:
        case 5:
          break;
        default:
          X = 3;
      }
      var I = w;
      w = X;
      try {
        return P();
      } finally {
        w = I;
      }
    }, c.unstable_scheduleCallback = function(X, P, I) {
      var pt = c.unstable_now();
      switch (typeof I == "object" && I !== null ? (I = I.delay, I = typeof I == "number" && 0 < I ? pt + I : pt) : I = pt, X) {
        case 1:
          var st = -1;
          break;
        case 2:
          st = 250;
          break;
        case 5:
          st = 1073741823;
          break;
        case 4:
          st = 1e4;
          break;
        default:
          st = 5e3;
      }
      return st = I + st, X = {
        id: z++,
        callback: P,
        priorityLevel: X,
        startTime: I,
        expirationTime: st,
        sortIndex: -1
      }, I > pt ? (X.sortIndex = I, r(M, X), y(q) === null && X === y(M) && (B ? (nt(V), V = -1) : B = !0, Rt(ft, I - pt))) : (X.sortIndex = st, r(q, X), F || Y || (F = !0, dt || (dt = !0, Lt()))), X;
    }, c.unstable_shouldYield = xt, c.unstable_wrapCallback = function(X) {
      var P = w;
      return function() {
        var I = w;
        w = P;
        try {
          return X.apply(this, arguments);
        } finally {
          w = I;
        }
      };
    };
  })(Gf)), Gf;
}
var Dh;
function Fv() {
  return Dh || (Dh = 1, Xf.exports = $v()), Xf.exports;
}
var Qf = { exports: {} }, se = {};
var Uh;
function Wv() {
  if (Uh) return se;
  Uh = 1;
  var c = Pf();
  function r(z) {
    var N = "https://react.dev/errors/" + z;
    if (1 < arguments.length) {
      N += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var w = 2; w < arguments.length; w++)
        N += "&args[]=" + encodeURIComponent(arguments[w]);
    }
    return "Minified React error #" + z + "; visit " + N + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function y() {
  }
  var o = {
    d: {
      f: y,
      r: function() {
        throw Error(r(522));
      },
      D: y,
      C: y,
      L: y,
      m: y,
      X: y,
      S: y,
      M: y
    },
    p: 0,
    findDOMNode: null
  }, h = /* @__PURE__ */ Symbol.for("react.portal"), D = /* @__PURE__ */ Symbol.for("react.recoverable"), R = /* @__PURE__ */ Symbol.for("react.optimistic_key");
  function p(z, N, w) {
    var Y = 3 < arguments.length && arguments[3] !== void 0 ? arguments[3] : null;
    return {
      $$typeof: h,
      key: Y == null ? null : Y === R ? R : "" + Y,
      children: z,
      containerInfo: N,
      implementation: w
    };
  }
  var q = c.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
  function M(z, N) {
    if (z === "font") return "";
    if (typeof N == "string")
      return N === "use-credentials" ? N : "";
  }
  return se.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = o, se.browser = function(z) {
    return { $$typeof: D, _reason: z };
  }, se.createPortal = function(z, N) {
    var w = 2 < arguments.length && arguments[2] !== void 0 ? arguments[2] : null;
    if (!N || N.nodeType !== 1 && N.nodeType !== 9 && N.nodeType !== 11)
      throw Error(r(299));
    return p(z, N, null, w);
  }, se.flushSync = function(z) {
    var N = q.T, w = o.p;
    try {
      if (q.T = null, o.p = 2, z) return z();
    } finally {
      q.T = N, o.p = w, o.d.f();
    }
  }, se.preconnect = function(z, N) {
    typeof z == "string" && (N ? (N = N.crossOrigin, N = typeof N == "string" ? N === "use-credentials" ? N : "" : void 0) : N = null, o.d.C(z, N));
  }, se.prefetchDNS = function(z) {
    typeof z == "string" && o.d.D(z);
  }, se.preinit = function(z, N) {
    if (typeof z == "string" && N && typeof N.as == "string") {
      var w = N.as, Y = M(w, N.crossOrigin), F = typeof N.integrity == "string" ? N.integrity : void 0, B = typeof N.fetchPriority == "string" ? N.fetchPriority : void 0;
      w === "style" ? o.d.S(
        z,
        typeof N.precedence == "string" ? N.precedence : void 0,
        {
          crossOrigin: Y,
          integrity: F,
          fetchPriority: B
        }
      ) : w === "script" && o.d.X(z, {
        crossOrigin: Y,
        integrity: F,
        fetchPriority: B,
        nonce: typeof N.nonce == "string" ? N.nonce : void 0
      });
    }
  }, se.preinitModule = function(z, N) {
    if (typeof z == "string")
      if (typeof N == "object" && N !== null) {
        if (N.as == null || N.as === "script") {
          var w = M(
            N.as,
            N.crossOrigin
          );
          o.d.M(z, {
            crossOrigin: w,
            integrity: typeof N.integrity == "string" ? N.integrity : void 0,
            nonce: typeof N.nonce == "string" ? N.nonce : void 0,
            fetchPriority: typeof N.fetchPriority == "string" ? N.fetchPriority : void 0
          });
        }
      } else N == null && o.d.M(z);
  }, se.preload = function(z, N) {
    if (typeof z == "string" && typeof N == "object" && N !== null && typeof N.as == "string") {
      var w = N.as, Y = M(w, N.crossOrigin);
      o.d.L(z, w, {
        crossOrigin: Y,
        integrity: typeof N.integrity == "string" ? N.integrity : void 0,
        nonce: typeof N.nonce == "string" ? N.nonce : void 0,
        type: typeof N.type == "string" ? N.type : void 0,
        fetchPriority: typeof N.fetchPriority == "string" ? N.fetchPriority : void 0,
        referrerPolicy: typeof N.referrerPolicy == "string" ? N.referrerPolicy : void 0,
        imageSrcSet: typeof N.imageSrcSet == "string" ? N.imageSrcSet : void 0,
        imageSizes: typeof N.imageSizes == "string" ? N.imageSizes : void 0,
        media: typeof N.media == "string" ? N.media : void 0
      });
    }
  }, se.preloadModule = function(z, N) {
    if (typeof z == "string")
      if (N) {
        var w = M(N.as, N.crossOrigin);
        o.d.m(z, {
          as: typeof N.as == "string" && N.as !== "script" ? N.as : void 0,
          crossOrigin: w,
          integrity: typeof N.integrity == "string" ? N.integrity : void 0,
          nonce: typeof N.nonce == "string" ? N.nonce : void 0,
          fetchPriority: typeof N.fetchPriority == "string" ? N.fetchPriority : void 0
        });
      } else o.d.m(z);
  }, se.requestFormReset = function(z) {
    o.d.r(z);
  }, se.unstable_batchedUpdates = function(z, N) {
    return z(N);
  }, se.useFormState = function(z, N, w) {
    return q.H.useFormState(z, N, w);
  }, se.useFormStatus = function() {
    return q.H.useHostTransitionStatus();
  }, se.version = "19.3.0", se;
}
var wh;
function Iv() {
  if (wh) return Qf.exports;
  wh = 1;
  function c() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(c);
      } catch (r) {
        console.error(r);
      }
  }
  return c(), Qf.exports = Wv(), Qf.exports;
}
var Hh;
function Pv() {
  if (Hh) return gu;
  Hh = 1;
  var c = Fv(), r = Pf(), y = Iv();
  function o(t) {
    var e = "https://react.dev/errors/" + t;
    if (1 < arguments.length) {
      e += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var l = 2; l < arguments.length; l++)
        e += "&args[]=" + encodeURIComponent(arguments[l]);
    }
    return "Minified React error #" + t + "; visit " + e + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function h(t) {
    return !(!t || t.nodeType !== 1 && t.nodeType !== 9 && t.nodeType !== 11);
  }
  function D(t) {
    for (var e = t, l = e; l && !l.alternate; )
      e = l, (e.flags & 4098) !== 0 && (t = e.return), l = e.return;
    for (; e.return; ) e = e.return;
    return e.tag === 3 ? t : null;
  }
  function R(t) {
    if (t.tag === 13) {
      var e = t.memoizedState;
      if (e === null && (t = t.alternate, t !== null && (e = t.memoizedState)), e !== null) return e.dehydrated;
    }
    return null;
  }
  function p(t) {
    if (t.tag === 31) {
      var e = t.memoizedState;
      if (e === null && (t = t.alternate, t !== null && (e = t.memoizedState)), e !== null) return e.dehydrated;
    }
    return null;
  }
  function q(t) {
    if (D(t) !== t)
      throw Error(o(188));
  }
  function M(t) {
    var e = t.alternate;
    if (!e) {
      if (e = D(t), e === null) throw Error(o(188));
      return e !== t ? null : t;
    }
    for (var l = t, a = e; ; ) {
      var n = l.return;
      if (n === null) break;
      var u = n.alternate;
      if (u === null) {
        if (a = n.return, a !== null) {
          l = a;
          continue;
        }
        break;
      }
      if (n.child === u.child) {
        for (u = n.child; u; ) {
          if (u === l) return q(n), t;
          if (u === a) return q(n), e;
          u = u.sibling;
        }
        throw Error(o(188));
      }
      if (l.return !== a.return) l = n, a = u;
      else {
        for (var i = !1, f = n.child; f; ) {
          if (f === l) {
            i = !0, l = n, a = u;
            break;
          }
          if (f === a) {
            i = !0, a = n, l = u;
            break;
          }
          f = f.sibling;
        }
        if (!i) {
          for (f = u.child; f; ) {
            if (f === l) {
              i = !0, l = u, a = n;
              break;
            }
            if (f === a) {
              i = !0, a = u, l = n;
              break;
            }
            f = f.sibling;
          }
          if (!i) throw Error(o(189));
        }
      }
      if (l.alternate !== a) throw Error(o(190));
    }
    if (l.tag !== 3) throw Error(o(188));
    return l.stateNode.current === l ? t : e;
  }
  function z(t) {
    var e = t.tag;
    if (e === 5 || e === 26 || e === 27 || e === 6) return t;
    for (t = t.child; t !== null; ) {
      if (e = z(t), e !== null) return e;
      t = t.sibling;
    }
    return null;
  }
  function N(t, e, l, a, n, u) {
    for (; t !== null; ) {
      if ((t.tag === 5 || t.tag === 27 || t.tag === 6) && l(t, a, n, u) || (t.tag !== 22 || t.memoizedState === null) && (e || t.tag !== 5 && t.tag !== 27) && N(
        t.child,
        e,
        l,
        a,
        n,
        u
      ))
        return !0;
      t = t.sibling;
    }
    return !1;
  }
  function w(t) {
    for (t = t.return; t !== null; ) {
      if (t.tag === 3 || t.tag === 5 || t.tag === 27) return t;
      t = t.return;
    }
    return null;
  }
  function Y(t) {
    var e = !1;
    for (t = t.return; t !== null && (t.tag === 4 && (e = !0), !(t.tag === 3 || t.tag === 5 || t.tag === 27)); )
      t = t.return;
    return e;
  }
  function F(t) {
    var e = [null, null], l = w(t);
    return l === null || B(
      e,
      t,
      l.child,
      { foundSelf: !1 }
    ), e;
  }
  function B(t, e, l, a) {
    for (; l !== null; ) {
      if (l === e) a.foundSelf = !0;
      else if (l.tag === 5 || l.tag === 27 || l.tag === 6) {
        if (a.foundSelf) return t[1] = l, !0;
        t[0] = l;
      } else if ((l.tag !== 22 || l.memoizedState === null) && B(
        t,
        e,
        l.child,
        a
      ))
        return !0;
      l = l.sibling;
    }
    return !1;
  }
  function Q(t) {
    switch (t.tag) {
      case 5:
      case 27:
      case 6:
        return t.stateNode;
      case 3:
        return t.stateNode.containerInfo;
      default:
        throw Error(o(559));
    }
  }
  var rt = null, nt = null;
  function wt(t, e, l) {
    return t === l ? !0 : t === e ? (rt = t, !0) : !1;
  }
  function bt(t, e, l) {
    return t === l ? (nt = t, !1) : t === e ? (nt !== null && (rt = t), !0) : !1;
  }
  function ft(t) {
    if (t === null) return null;
    do
      t = t === null ? null : t.return;
    while (t && t.tag !== 5 && t.tag !== 27 && t.tag !== 3);
    return t || null;
  }
  function dt(t, e, l) {
    for (var a = 0, n = t; n; n = l(n)) a++;
    n = 0;
    for (var u = e; u; u = l(u)) n++;
    for (; 0 < a - n; ) t = l(t), a--;
    for (; 0 < n - a; ) e = l(e), n--;
    for (; a--; ) {
      if (t === e || e !== null && t === e.alternate)
        return t;
      t = l(t), e = l(e);
    }
    return null;
  }
  var V = Object.assign, k = /* @__PURE__ */ Symbol.for("react.element"), qt = /* @__PURE__ */ Symbol.for("react.transitional.element"), xt = /* @__PURE__ */ Symbol.for("react.portal"), Yt = /* @__PURE__ */ Symbol.for("react.fragment"), Lt = /* @__PURE__ */ Symbol.for("react.strict_mode"), Ht = /* @__PURE__ */ Symbol.for("react.profiler"), $t = /* @__PURE__ */ Symbol.for("react.consumer"), Rt = /* @__PURE__ */ Symbol.for("react.context"), X = /* @__PURE__ */ Symbol.for("react.forward_ref"), P = /* @__PURE__ */ Symbol.for("react.suspense"), I = /* @__PURE__ */ Symbol.for("react.suspense_list"), pt = /* @__PURE__ */ Symbol.for("react.memo"), st = /* @__PURE__ */ Symbol.for("react.lazy"), ee = /* @__PURE__ */ Symbol.for("react.activity"), Se = /* @__PURE__ */ Symbol.for("react.legacy_hidden"), A = /* @__PURE__ */ Symbol.for("react.memo_cache_sentinel"), d = /* @__PURE__ */ Symbol.for("react.view_transition"), E = /* @__PURE__ */ Symbol.for("react.recoverable"), _ = Symbol.iterator;
  function U(t) {
    return t === null || typeof t != "object" ? null : (t = _ && t[_] || t["@@iterator"], typeof t == "function" ? t : null);
  }
  var H = /* @__PURE__ */ Symbol.for("react.client.reference");
  function K(t) {
    if (t == null) return null;
    if (typeof t == "function")
      return t.$$typeof === H ? null : t.displayName || t.name || null;
    if (typeof t == "string") return t;
    switch (t) {
      case Yt:
        return "Fragment";
      case Ht:
        return "Profiler";
      case Lt:
        return "StrictMode";
      case P:
        return "Suspense";
      case I:
        return "SuspenseList";
      case ee:
        return "Activity";
      case d:
        return "ViewTransition";
    }
    if (typeof t == "object")
      switch (t.$$typeof) {
        case xt:
          return "Portal";
        case Rt:
          return t.displayName || "Context";
        case $t:
          return (t._context.displayName || "Context") + ".Consumer";
        case X:
          var e = t.render;
          return t = t.displayName, t || (t = e.displayName || e.name || "", t = t !== "" ? "ForwardRef(" + t + ")" : "ForwardRef"), t;
        case pt:
          return e = t.displayName || null, e !== null ? e : K(t.type) || "Memo";
        case st:
          e = t._payload, t = t._init;
          try {
            return K(t(e));
          } catch {
          }
      }
    return null;
  }
  var et = Array.isArray, G = r.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, W = y.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, Dt = {
    pending: !1,
    data: null,
    method: null,
    action: null
  }, dl = [], Ke = -1;
  function we(t) {
    return { current: t };
  }
  function Qt(t) {
    0 > Ke || (t.current = dl[Ke], dl[Ke] = null, Ke--);
  }
  function Ot(t, e) {
    Ke++, dl[Ke] = t.current, t.current = e;
  }
  var Pe = we(null), Nn = we(null), Al = we(null), Nu = we(null);
  function Tu(t, e) {
    switch (Ot(Al, e), Ot(Nn, t), Ot(Pe, null), e.nodeType) {
      case 9:
      case 11:
        t = (t = e.documentElement) && (t = t.namespaceURI) ? Ym(t) : 0;
        break;
      default:
        if (t = e.tagName, e = e.namespaceURI)
          e = Ym(e), t = Lm(e, t);
        else
          switch (t) {
            case "svg":
              t = 1;
              break;
            case "math":
              t = 2;
              break;
            default:
              t = 0;
          }
    }
    Qt(Pe), Ot(Pe, t);
  }
  function Aa() {
    Qt(Pe), Qt(Nn), Qt(Al);
  }
  function nc(t) {
    var e = t.memoizedState;
    e !== null && (vn._currentValue = e.memoizedState, Ot(Nu, t)), e = Pe.current;
    var l = Lm(e, t.type);
    e !== l && (Ot(Nn, t), Ot(Pe, l));
  }
  function Eu(t) {
    Nn.current === t && (Qt(Pe), Qt(Nn)), Nu.current === t && (Qt(Nu), vn._currentValue = Dt);
  }
  var uc, uo;
  function Ol(t) {
    if (uc === void 0)
      try {
        throw Error();
      } catch (l) {
        var e = l.stack.trim().match(/\n( *(at )?)/);
        uc = e && e[1] || "", uo = -1 < l.stack.indexOf(`
    at`) ? " (<anonymous>)" : -1 < l.stack.indexOf("@") ? "@unknown:0:0" : "";
      }
    return `
` + uc + t + uo;
  }
  var ic = !1;
  function cc(t, e) {
    if (!t || ic) return "";
    ic = !0;
    var l = Error.prepareStackTrace;
    Error.prepareStackTrace = void 0;
    try {
      var a = {
        DetermineComponentFrameRoot: function() {
          try {
            if (e) {
              var C = function() {
                throw Error();
              };
              if (Object.defineProperty(C.prototype, "props", {
                set: function() {
                  throw Error();
                }
              }), typeof Reflect == "object" && Reflect.construct) {
                try {
                  Reflect.construct(C, []);
                } catch (L) {
                  var g = L;
                }
                Reflect.construct(t, [], C);
              } else {
                try {
                  C.call();
                } catch (L) {
                  g = L;
                }
                C = !1;
                try {
                  var T = Object.getOwnPropertyDescriptor(
                    t.prototype,
                    "props"
                  );
                  Object.defineProperty(t.prototype, "props", {
                    configurable: !0,
                    set: function() {
                      throw Error();
                    }
                  }), C = !0, new t();
                } finally {
                  C && (T !== void 0 ? Object.defineProperty(t.prototype, "props", T) : delete t.prototype.props);
                }
              }
            } else {
              try {
                throw Error();
              } catch (L) {
                g = L;
              }
              (C = t()) && typeof C.catch == "function" && C.catch(function() {
              });
            }
          } catch (L) {
            if (L && g && typeof L.stack == "string")
              return [L.stack, g.stack];
          }
          return [null, null];
        }
      };
      a.DetermineComponentFrameRoot.displayName = "DetermineComponentFrameRoot";
      var n = Object.getOwnPropertyDescriptor(
        a.DetermineComponentFrameRoot,
        "name"
      );
      n && n.configurable && Object.defineProperty(
        a.DetermineComponentFrameRoot,
        "name",
        { value: "DetermineComponentFrameRoot" }
      );
      var u = a.DetermineComponentFrameRoot(), i = u[0], f = u[1];
      if (i && f) {
        var m = i.split(`
`), x = f.split(`
`);
        for (n = a = 0; a < m.length && !m[a].includes("DetermineComponentFrameRoot"); )
          a++;
        for (; n < x.length && !x[n].includes(
          "DetermineComponentFrameRoot"
        ); )
          n++;
        if (a === m.length || n === x.length)
          for (a = m.length - 1, n = x.length - 1; 1 <= a && 0 <= n && m[a] !== x[n]; )
            n--;
        for (; 1 <= a && 0 <= n; a--, n--)
          if (m[a] !== x[n]) {
            if (a !== 1 || n !== 1)
              do
                if (a--, n--, 0 > n || m[a] !== x[n]) {
                  var j = `
` + m[a].replace(" at new ", " at ");
                  return t.displayName && j.includes("<anonymous>") && (j = j.replace("<anonymous>", t.displayName)), j;
                }
              while (1 <= a && 0 <= n);
            break;
          }
      }
    } finally {
      ic = !1, Error.prepareStackTrace = l;
    }
    return (l = t ? t.displayName || t.name : "") ? Ol(l) : "";
  }
  function Ih(t, e) {
    switch (t.tag) {
      case 26:
      case 27:
      case 5:
        return Ol(t.type);
      case 16:
        return Ol("Lazy");
      case 13:
        return t.child !== e && e !== null ? Ol("Suspense Fallback") : Ol("Suspense");
      case 19:
        return Ol("SuspenseList");
      case 0:
      case 15:
        return cc(t.type, !1);
      case 11:
        return cc(t.type.render, !1);
      case 1:
        return cc(t.type, !0);
      case 31:
        return Ol("Activity");
      case 30:
        return Ol("ViewTransition");
      default:
        return "";
    }
  }
  function io(t) {
    try {
      var e = "", l = null;
      do
        e += Ih(t, l), l = t, t = t.return;
      while (t);
      return e;
    } catch (a) {
      return `
Error generating stack: ` + a.message + `
` + a.stack;
    }
  }
  var sc = Object.prototype.hasOwnProperty, fc = c.unstable_scheduleCallback, oc = c.unstable_cancelCallback, Ph = c.unstable_shouldYield, t0 = c.unstable_requestPaint, _e = c.unstable_now, e0 = c.unstable_getCurrentPriorityLevel, co = c.unstable_ImmediatePriority, so = c.unstable_UserBlockingPriority, ju = c.unstable_NormalPriority, l0 = c.unstable_LowPriority, fo = c.unstable_IdlePriority, a0 = c.log, n0 = c.unstable_setDisableYieldValue, Tn = null, Ne = null;
  function Ml(t) {
    if (typeof a0 == "function" && n0(t), Ne && typeof Ne.setStrictMode == "function")
      try {
        Ne.setStrictMode(Tn, t);
      } catch {
      }
  }
  var Te = Math.clz32 ? Math.clz32 : c0, u0 = Math.log, i0 = Math.LN2;
  function c0(t) {
    return t >>>= 0, t === 0 ? 32 : 31 - (u0(t) / i0 | 0) | 0;
  }
  var zu = 256, Au = 262144, Ou = 4194304;
  function na(t) {
    var e = t & 42;
    if (e !== 0) return e;
    switch (t & -t) {
      case 1:
        return 1;
      case 2:
        return 2;
      case 4:
        return 4;
      case 8:
        return 8;
      case 16:
        return 16;
      case 32:
        return 32;
      case 64:
        return 64;
      case 128:
        return 128;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
        return t & -t;
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return t & 3932160;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return t & 62914560;
      case 67108864:
        return 67108864;
      case 134217728:
        return 134217728;
      case 268435456:
        return 268435456;
      case 536870912:
        return 536870912;
      case 1073741824:
        return 0;
      default:
        return t;
    }
  }
  function Mu(t, e, l) {
    var a = t.pendingLanes;
    if (a === 0) return 0;
    var n = 0, u = t.suspendedLanes, i = t.pingedLanes;
    t = t.warmLanes;
    var f = a & 134217727;
    return f !== 0 ? (a = f & ~u, a !== 0 ? n = na(a) : (i &= f, i !== 0 ? n = na(i) : l || (l = f & ~t, l !== 0 && (n = na(l))))) : (f = a & ~u, f !== 0 ? n = na(f) : i !== 0 ? n = na(i) : l || (l = a & ~t, l !== 0 && (n = na(l)))), n === 0 ? 0 : e !== 0 && e !== n && (e & u) === 0 && (u = n & -n, l = e & -e, u >= l || u === 32 && (l & 4194048) !== 0) ? e : n;
  }
  function En(t, e) {
    return (t.pendingLanes & ~(t.suspendedLanes & ~t.pingedLanes) & e) === 0;
  }
  function oo(t, e) {
    (e & 8) !== 0 && (e |= e & 32);
    var l = t.entangledLanes;
    if (l !== 0)
      for (t = t.entanglements, l &= e; 0 < l; ) {
        var a = 31 - Te(l), n = 1 << a;
        e |= t[a], l &= ~n;
      }
    return e;
  }
  function s0(t, e) {
    switch (t) {
      case 1:
      case 2:
      case 4:
      case 8:
      case 64:
        return e + 250;
      case 16:
      case 32:
      case 128:
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return e + 5e3;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return -1;
      case 67108864:
      case 134217728:
      case 268435456:
      case 536870912:
      case 1073741824:
        return -1;
      default:
        return -1;
    }
  }
  function ro() {
    var t = Ou;
    return Ou <<= 1, (Ou & 62914560) === 0 && (Ou = 4194304), t;
  }
  function rc(t) {
    for (var e = [], l = 0; 31 > l; l++) e.push(t);
    return e;
  }
  function jn(t, e) {
    t.pendingLanes |= e, e !== 268435456 && (t.suspendedLanes = 0, t.pingedLanes = 0, t.warmLanes = 0);
  }
  function f0(t, e, l, a, n, u) {
    var i = t.pendingLanes;
    t.pendingLanes = l, t.suspendedLanes = 0, t.pingedLanes = 0, t.warmLanes = 0, t.expiredLanes &= l, t.entangledLanes &= l, t.errorRecoveryDisabledLanes &= l, t.shellSuspendCounter = 0;
    var f = t.entanglements, m = t.expirationTimes, x = t.hiddenUpdates;
    for (l = i & ~l; 0 < l; ) {
      var j = 31 - Te(l), C = 1 << j;
      f[j] = 0, m[j] = -1;
      var g = x[j];
      if (g !== null)
        for (x[j] = null, j = 0; j < g.length; j++) {
          var T = g[j];
          T !== null && (T.lane &= -536870913);
        }
      l &= ~C;
    }
    a !== 0 && mo(t, a, 0), u !== 0 && n === 0 && t.tag !== 0 && (t.suspendedLanes |= u & ~(i & ~e));
  }
  function mo(t, e, l) {
    t.pendingLanes |= e, t.suspendedLanes &= ~e;
    var a = 31 - Te(e);
    t.entangledLanes |= e, t.entanglements[a] = t.entanglements[a] | 1073741824 | l & 261930;
  }
  function ho(t, e) {
    var l = t.entangledLanes |= e;
    for (t = t.entanglements; l; ) {
      var a = 31 - Te(l), n = 1 << a;
      n & e | t[a] & e && (t[a] |= e), l &= ~n;
    }
  }
  function yo(t, e) {
    var l = e & -e;
    return l = (l & 42) !== 0 ? 1 : dc(l), (l & (t.suspendedLanes | e)) !== 0 ? 0 : l;
  }
  function dc(t) {
    switch (t) {
      case 2:
        t = 1;
        break;
      case 8:
        t = 4;
        break;
      case 32:
        t = 16;
        break;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        t = 128;
        break;
      case 268435456:
        t = 134217728;
        break;
      default:
        t = 0;
    }
    return t;
  }
  function mc(t) {
    return t &= -t, 2 < t ? 8 < t ? (t & 134217727) !== 0 ? 32 : 268435456 : 8 : 2;
  }
  function vo() {
    var t = W.p;
    return t !== 0 ? t : (t = window.event, t === void 0 ? 32 : Nh(t.type));
  }
  function go(t, e) {
    var l = W.p;
    try {
      return W.p = t, e();
    } finally {
      W.p = l;
    }
  }
  var ml = Math.random().toString(36).slice(2), le = "__reactFiber$" + ml, ye = "__reactProps$" + ml, Oa = "__reactContainer$" + ml, po = "__reactEvents$" + ml, o0 = "__reactListeners$" + ml, r0 = "__reactHandles$" + ml, bo = "__reactResources$" + ml, zn = "__reactMarker$" + ml, Cu = "__reactLoad$" + ml;
  function Ru(t) {
    delete t[le], delete t[ye], delete t[o0], delete t[r0];
  }
  function ua(t) {
    var e;
    if (e = t[le]) return e;
    for (var l = t.parentNode; l; ) {
      if (e = l[Oa] || l[le]) {
        if (l = e.alternate, e.child !== null || l !== null && l.child !== null)
          for (t = ah(t); t !== null; ) {
            if (l = t[le]) return l;
            t = ah(t);
          }
        return e;
      }
      t = l, l = t.parentNode;
    }
    return null;
  }
  function Ma(t) {
    if (t = t[le] || t[Oa]) {
      var e = t.tag;
      if (e === 5 || e === 6 || e === 13 || e === 31 || e === 26 || e === 27 || e === 3)
        return t;
    }
    return null;
  }
  function An(t) {
    var e = t.tag;
    if (e === 5 || e === 26 || e === 27 || e === 6) return t.stateNode;
    throw Error(o(33));
  }
  function Ca(t) {
    var e = t[bo];
    return e || (e = t[bo] = { hoistableStyles: /* @__PURE__ */ new Map(), hoistableScripts: /* @__PURE__ */ new Map() }), e;
  }
  function Wt(t) {
    t[zn] = !0;
  }
  function xo(t) {
    t[Cu] = void 0;
  }
  var So = /* @__PURE__ */ new Set(), _o = {};
  function ia(t, e) {
    Ra(t, e), Ra(t + "Capture", e);
  }
  function Ra(t, e) {
    for (_o[t] = e, t = 0; t < e.length; t++)
      So.add(e[t]);
  }
  var d0 = RegExp(
    "^[:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD][:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD\\-.0-9\\u00B7\\u0300-\\u036F\\u203F-\\u2040]*$"
  ), No = {}, To = {};
  function m0(t) {
    return sc.call(To, t) ? !0 : sc.call(No, t) ? !1 : d0.test(t) ? To[t] = !0 : (No[t] = !0, !1);
  }
  var St = !1;
  function Eo() {
    var t = St;
    return St = !1, t;
  }
  function Du(t, e, l) {
    if (m0(e))
      if (l === null) t.removeAttribute(e);
      else {
        switch (typeof l) {
          case "undefined":
          case "function":
          case "symbol":
            t.removeAttribute(e);
            return;
          case "boolean":
            var a = e.toLowerCase().slice(0, 5);
            if (a !== "data-" && a !== "aria-") {
              t.removeAttribute(e);
              return;
            }
        }
        t.setAttribute(e, l);
      }
  }
  function Uu(t, e, l) {
    if (l === null) t.removeAttribute(e);
    else {
      switch (typeof l) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          t.removeAttribute(e);
          return;
      }
      t.setAttribute(e, l);
    }
  }
  function hl(t, e, l, a) {
    if (a === null) t.removeAttribute(l);
    else {
      switch (typeof a) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          t.removeAttribute(l);
          return;
      }
      t.setAttributeNS(e, l, a);
    }
  }
  function Ee(t) {
    switch (typeof t) {
      case "bigint":
      case "boolean":
      case "number":
      case "string":
      case "undefined":
        return t;
      case "object":
        return t;
      default:
        return "";
    }
  }
  function jo(t) {
    var e = t.type;
    return (t = t.nodeName) && t.toLowerCase() === "input" && (e === "checkbox" || e === "radio");
  }
  function h0(t, e, l) {
    var a = Object.getOwnPropertyDescriptor(
      t.constructor.prototype,
      e
    );
    if (!t.hasOwnProperty(e) && typeof a < "u" && typeof a.get == "function" && typeof a.set == "function") {
      var n = a.get, u = a.set;
      return Object.defineProperty(t, e, {
        configurable: !0,
        get: function() {
          return n.call(this);
        },
        set: function(i) {
          l = "" + i, u.call(this, i);
        }
      }), Object.defineProperty(t, e, {
        enumerable: a.enumerable
      }), {
        getValue: function() {
          return l;
        },
        setValue: function(i) {
          l = "" + i;
        },
        stopTracking: function() {
          t._valueTracker = null, delete t[e];
        }
      };
    }
  }
  function hc(t) {
    if (!t._valueTracker) {
      var e = jo(t) ? "checked" : "value";
      t._valueTracker = h0(
        t,
        e,
        "" + t[e]
      );
    }
  }
  function zo(t) {
    if (!t) return !1;
    var e = t._valueTracker;
    if (!e) return !0;
    var l = e.getValue(), a = "";
    return t && (a = jo(t) ? t.checked ? "true" : "false" : t.value), t = a, t !== l ? (e.setValue(t), !0) : !1;
  }
  var y0 = /[\n"\\]/g;
  function He(t) {
    return t.replace(
      y0,
      function(e) {
        return "\\" + e.charCodeAt(0).toString(16) + " ";
      }
    );
  }
  function yc(t, e, l, a, n, u, i, f) {
    t.name = "", i != null && typeof i != "function" && typeof i != "symbol" && typeof i != "boolean" ? t.type = i : t.removeAttribute("type"), e != null ? i === "number" ? (e === 0 && t.value === "" || t.value != e) && (t.value = "" + Ee(e)) : t.value !== "" + Ee(e) && (t.value = "" + Ee(e)) : i !== "submit" && i !== "reset" || t.removeAttribute("value"), e != null ? i === "number" && t.value == e ? vc(t, Ee(t.value)) : vc(t, Ee(e)) : l != null ? vc(t, Ee(l)) : a != null && t.removeAttribute("value"), n == null && u != null && (t.defaultChecked = !!u), n != null && (t.checked = n && typeof n != "function" && typeof n != "symbol"), f != null && typeof f != "function" && typeof f != "symbol" && typeof f != "boolean" ? t.name = "" + Ee(f) : t.removeAttribute("name");
  }
  function Ao(t, e, l, a, n, u, i, f) {
    if (u != null && typeof u != "function" && typeof u != "symbol" && typeof u != "boolean" && (t.type = u), e != null || l != null) {
      if (!(u !== "submit" && u !== "reset" || e != null)) {
        hc(t);
        return;
      }
      l = l != null ? "" + Ee(l) : "", e = e != null ? "" + Ee(e) : l, f || e === t.value || (t.value = e), t.defaultValue = e;
    }
    a = a ?? n, a = typeof a != "function" && typeof a != "symbol" && !!a, t.checked = f ? t.checked : !!a, t.defaultChecked = !!a, i != null && typeof i != "function" && typeof i != "symbol" && typeof i != "boolean" && (t.name = i), hc(t);
  }
  function vc(t, e) {
    t.defaultValue !== "" + e && (t.defaultValue = "" + e);
  }
  function Da(t, e, l, a) {
    if (t = t.options, e) {
      e = {};
      for (var n = 0; n < l.length; n++)
        e["$" + l[n]] = !0;
      for (l = 0; l < t.length; l++)
        n = e.hasOwnProperty("$" + t[l].value), t[l].selected !== n && (t[l].selected = n), n && a && (t[l].defaultSelected = !0);
    } else {
      for (l = "" + Ee(l), e = null, n = 0; n < t.length; n++) {
        if (t[n].value === l) {
          t[n].selected = !0, a && (t[n].defaultSelected = !0);
          return;
        }
        e !== null || t[n].disabled || (e = t[n]);
      }
      e !== null && (e.selected = !0);
    }
  }
  function Oo(t, e, l) {
    if (e != null && (e = "" + Ee(e), e !== t.value && (t.value = e), l == null)) {
      t.defaultValue !== e && (t.defaultValue = e);
      return;
    }
    t.defaultValue = l != null ? "" + Ee(l) : "";
  }
  function Mo(t, e, l, a) {
    if (e == null) {
      if (a != null) {
        if (l != null) throw Error(o(92));
        if (et(a)) {
          if (1 < a.length) throw Error(o(93));
          a = a[0];
        }
        l = a;
      }
      l == null && (l = ""), e = l;
    }
    l = Ee(e), t.defaultValue = l, a = t.textContent, a === l && a !== "" && a !== null && (t.value = a), hc(t);
  }
  function Ua(t, e) {
    if (e) {
      var l = t.firstChild;
      if (l && l === t.lastChild && l.nodeType === 3) {
        l.nodeValue = e;
        return;
      }
    }
    t.textContent = e;
  }
  var v0 = new Set(
    "animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth MozAnimationIterationCount MozBoxFlex MozBoxFlexGroup MozLineClamp msAnimationIterationCount msFlex msZoom msFlexGrow msFlexNegative msFlexOrder msFlexPositive msFlexShrink msGridColumn msGridColumnSpan msGridRow msGridRowSpan WebkitAnimationIterationCount WebkitBoxFlex WebKitBoxFlexGroup WebkitBoxOrdinalGroup WebkitColumnCount WebkitColumns WebkitFlex WebkitFlexGrow WebkitFlexPositive WebkitFlexShrink WebkitLineClamp".split(
      " "
    )
  );
  function Co(t, e, l) {
    var a = e.indexOf("--") === 0;
    l == null || typeof l == "boolean" || l === "" ? a ? t.setProperty(e, "") : e === "float" ? t.cssFloat = "" : t[e] = "" : a ? t.setProperty(e, l) : typeof l != "number" || l === 0 || v0.has(e) ? e === "float" ? t.cssFloat = l : t[e] = ("" + l).trim() : t[e] = l + "px";
  }
  function Ro(t, e, l) {
    if (e != null && typeof e != "object")
      throw Error(o(62));
    if (t = t.style, l != null) {
      for (var a in l)
        !l.hasOwnProperty(a) || e != null && e.hasOwnProperty(a) || (a.indexOf("--") === 0 ? t.setProperty(a, "") : a === "float" ? t.cssFloat = "" : t[a] = "", St = !0);
      for (var n in e)
        a = e[n], e.hasOwnProperty(n) && l[n] !== a && (Co(t, n, a), St = !0);
    } else
      for (var u in e)
        e.hasOwnProperty(u) && Co(t, u, e[u]);
  }
  function gc(t) {
    if (t.indexOf("-") === -1) return !1;
    switch (t) {
      case "annotation-xml":
      case "color-profile":
      case "font-face":
      case "font-face-src":
      case "font-face-uri":
      case "font-face-format":
      case "font-face-name":
      case "missing-glyph":
        return !1;
      default:
        return !0;
    }
  }
  var g0 = /* @__PURE__ */ new Map([
    ["acceptCharset", "accept-charset"],
    ["htmlFor", "for"],
    ["httpEquiv", "http-equiv"],
    ["crossOrigin", "crossorigin"],
    ["accentHeight", "accent-height"],
    ["alignmentBaseline", "alignment-baseline"],
    ["arabicForm", "arabic-form"],
    ["baselineShift", "baseline-shift"],
    ["capHeight", "cap-height"],
    ["clipPath", "clip-path"],
    ["clipRule", "clip-rule"],
    ["colorInterpolation", "color-interpolation"],
    ["colorInterpolationFilters", "color-interpolation-filters"],
    ["colorProfile", "color-profile"],
    ["colorRendering", "color-rendering"],
    ["dominantBaseline", "dominant-baseline"],
    ["enableBackground", "enable-background"],
    ["fillOpacity", "fill-opacity"],
    ["fillRule", "fill-rule"],
    ["floodColor", "flood-color"],
    ["floodOpacity", "flood-opacity"],
    ["fontFamily", "font-family"],
    ["fontSize", "font-size"],
    ["fontSizeAdjust", "font-size-adjust"],
    ["fontStretch", "font-stretch"],
    ["fontStyle", "font-style"],
    ["fontVariant", "font-variant"],
    ["fontWeight", "font-weight"],
    ["glyphName", "glyph-name"],
    ["glyphOrientationHorizontal", "glyph-orientation-horizontal"],
    ["glyphOrientationVertical", "glyph-orientation-vertical"],
    ["horizAdvX", "horiz-adv-x"],
    ["horizOriginX", "horiz-origin-x"],
    ["imageRendering", "image-rendering"],
    ["letterSpacing", "letter-spacing"],
    ["lightingColor", "lighting-color"],
    ["markerEnd", "marker-end"],
    ["markerMid", "marker-mid"],
    ["markerStart", "marker-start"],
    ["maskType", "mask-type"],
    ["overlinePosition", "overline-position"],
    ["overlineThickness", "overline-thickness"],
    ["paintOrder", "paint-order"],
    ["panose-1", "panose-1"],
    ["pointerEvents", "pointer-events"],
    ["renderingIntent", "rendering-intent"],
    ["shapeRendering", "shape-rendering"],
    ["stopColor", "stop-color"],
    ["stopOpacity", "stop-opacity"],
    ["strikethroughPosition", "strikethrough-position"],
    ["strikethroughThickness", "strikethrough-thickness"],
    ["strokeDasharray", "stroke-dasharray"],
    ["strokeDashoffset", "stroke-dashoffset"],
    ["strokeLinecap", "stroke-linecap"],
    ["strokeLinejoin", "stroke-linejoin"],
    ["strokeMiterlimit", "stroke-miterlimit"],
    ["strokeOpacity", "stroke-opacity"],
    ["strokeWidth", "stroke-width"],
    ["textAnchor", "text-anchor"],
    ["textDecoration", "text-decoration"],
    ["textRendering", "text-rendering"],
    ["transformOrigin", "transform-origin"],
    ["underlinePosition", "underline-position"],
    ["underlineThickness", "underline-thickness"],
    ["unicodeBidi", "unicode-bidi"],
    ["unicodeRange", "unicode-range"],
    ["unitsPerEm", "units-per-em"],
    ["vAlphabetic", "v-alphabetic"],
    ["vHanging", "v-hanging"],
    ["vIdeographic", "v-ideographic"],
    ["vMathematical", "v-mathematical"],
    ["vectorEffect", "vector-effect"],
    ["vertAdvY", "vert-adv-y"],
    ["vertOriginX", "vert-origin-x"],
    ["vertOriginY", "vert-origin-y"],
    ["wordSpacing", "word-spacing"],
    ["writingMode", "writing-mode"],
    ["xmlnsXlink", "xmlns:xlink"],
    ["xHeight", "x-height"]
  ]), p0 = /^[\u0000-\u001F ]*j[\r\n\t]*a[\r\n\t]*v[\r\n\t]*a[\r\n\t]*s[\r\n\t]*c[\r\n\t]*r[\r\n\t]*i[\r\n\t]*p[\r\n\t]*t[\r\n\t]*:/i;
  function wu(t) {
    return p0.test("" + t) ? "javascript:throw new Error('React has blocked a javascript: URL as a security precaution.')" : t;
  }
  function tl() {
  }
  var pc = null;
  function bc(t) {
    return t = t.target || t.srcElement || window, t.correspondingUseElement && (t = t.correspondingUseElement), t.nodeType === 3 ? t.parentNode : t;
  }
  var wa = null, Ha = null;
  function Do(t) {
    var e = Ma(t);
    if (e && (t = e.stateNode)) {
      var l = t[ye] || null;
      t: switch (t = e.stateNode, e.type) {
        case "input":
          if (yc(
            t,
            l.value,
            l.defaultValue,
            l.defaultValue,
            l.checked,
            l.defaultChecked,
            l.type,
            l.name
          ), e = l.name, l.type === "radio" && e != null) {
            for (l = t; l.parentNode; ) l = l.parentNode;
            for (l = l.querySelectorAll(
              'input[name="' + He(
                "" + e
              ) + '"][type="radio"]'
            ), e = 0; e < l.length; e++) {
              var a = l[e];
              if (a !== t && a.form === t.form) {
                var n = a[ye] || null;
                if (!n) throw Error(o(90));
                yc(
                  a,
                  n.value,
                  n.defaultValue,
                  n.defaultValue,
                  n.checked,
                  n.defaultChecked,
                  n.type,
                  n.name
                );
              }
            }
            for (e = 0; e < l.length; e++)
              a = l[e], a.form === t.form && zo(a);
          }
          break t;
        case "textarea":
          Oo(t, l.value, l.defaultValue);
          break t;
        case "select":
          e = l.value, e != null && Da(t, !!l.multiple, e, !1);
      }
    }
  }
  var xc = !1;
  function Uo(t, e, l) {
    if (xc) return t(e, l);
    xc = !0;
    try {
      var a = t(e);
      return a;
    } finally {
      if (xc = !1, (wa !== null || Ha !== null) && (wi(), wa && (e = wa, t = Ha, Ha = wa = null, Do(e), t)))
        for (e = 0; e < t.length; e++) Do(t[e]);
    }
  }
  function On(t, e) {
    var l = t.stateNode;
    if (l === null) return null;
    var a = l[ye] || null;
    if (a === null) return null;
    l = a[e];
    t: switch (e) {
      case "onClick":
      case "onClickCapture":
      case "onDoubleClick":
      case "onDoubleClickCapture":
      case "onMouseDown":
      case "onMouseDownCapture":
      case "onMouseMove":
      case "onMouseMoveCapture":
      case "onMouseUp":
      case "onMouseUpCapture":
      case "onMouseEnter":
        (a = !a.disabled) || (t = t.type, a = !(t === "button" || t === "input" || t === "select" || t === "textarea")), t = !a;
        break t;
      default:
        t = !1;
    }
    if (t) return null;
    if (l && typeof l != "function")
      throw Error(
        o(231, e, typeof l)
      );
    return l;
  }
  var yl = !(typeof window > "u" || typeof window.document > "u" || typeof window.document.createElement > "u"), Sc = !1;
  if (yl)
    try {
      var Mn = {};
      Object.defineProperty(Mn, "passive", {
        get: function() {
          Sc = !0;
        }
      }), window.addEventListener("test", Mn, Mn), window.removeEventListener("test", Mn, Mn);
    } catch {
      Sc = !1;
    }
  var Cl = null, _c = null, Hu = null;
  function wo() {
    if (Hu) return Hu;
    var t, e = _c, l = e.length, a, n = "value" in Cl ? Cl.value : Cl.textContent, u = n.length;
    for (t = 0; t < l && e[t] === n[t]; t++) ;
    var i = l - t;
    for (a = 1; a <= i && e[l - a] === n[u - a]; a++) ;
    return Hu = n.slice(t, 1 < a ? 1 - a : void 0);
  }
  function Bu(t) {
    var e = t.keyCode;
    return "charCode" in t ? (t = t.charCode, t === 0 && e === 13 && (t = 13)) : t = e, t === 10 && (t = 13), 32 <= t || t === 13 ? t : 0;
  }
  function qu() {
    return !0;
  }
  function Ho() {
    return !1;
  }
  function oe(t) {
    function e(l, a, n, u, i) {
      this._reactName = l, this._targetInst = n, this.type = a, this.nativeEvent = u, this.target = i, this.currentTarget = null;
      for (var f in t)
        t.hasOwnProperty(f) && (l = t[f], this[f] = l ? l(u) : u[f]);
      return this.isDefaultPrevented = (u.defaultPrevented != null ? u.defaultPrevented : u.returnValue === !1) ? qu : Ho, this.isPropagationStopped = Ho, this;
    }
    return V(e.prototype, {
      preventDefault: function() {
        this.defaultPrevented = !0;
        var l = this.nativeEvent;
        l && (l.preventDefault ? l.preventDefault() : typeof l.returnValue != "unknown" && (l.returnValue = !1), this.isDefaultPrevented = qu);
      },
      stopPropagation: function() {
        var l = this.nativeEvent;
        l && (l.stopPropagation ? l.stopPropagation() : typeof l.cancelBubble != "unknown" && (l.cancelBubble = !0), this.isPropagationStopped = qu);
      },
      persist: function() {
      },
      isPersistent: qu
    }), e;
  }
  var Rl = {
    eventPhase: 0,
    bubbles: 0,
    cancelable: 0,
    timeStamp: function(t) {
      return t.timeStamp || Date.now();
    },
    defaultPrevented: 0,
    isTrusted: 0
  }, Yu = oe(Rl), Cn = V({}, Rl, { view: 0, detail: 0 }), b0 = oe(Cn), Nc, Tc, Rn, Lu = V({}, Cn, {
    screenX: 0,
    screenY: 0,
    clientX: 0,
    clientY: 0,
    pageX: 0,
    pageY: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    getModifierState: jc,
    button: 0,
    buttons: 0,
    relatedTarget: function(t) {
      return t.relatedTarget === void 0 ? t.fromElement === t.srcElement ? t.toElement : t.fromElement : t.relatedTarget;
    },
    movementX: function(t) {
      return "movementX" in t ? t.movementX : (t !== Rn && (Rn && t.type === "mousemove" ? (Nc = t.screenX - Rn.screenX, Tc = t.screenY - Rn.screenY) : Tc = Nc = 0, Rn = t), Nc);
    },
    movementY: function(t) {
      return "movementY" in t ? t.movementY : Tc;
    }
  }), Bo = oe(Lu), x0 = V({}, Lu, { dataTransfer: 0 }), S0 = oe(x0), _0 = V({}, Cn, { relatedTarget: 0 }), Ec = oe(_0), N0 = V({}, Rl, {
    animationName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), T0 = oe(N0), E0 = V({}, Rl, {
    clipboardData: function(t) {
      return "clipboardData" in t ? t.clipboardData : window.clipboardData;
    }
  }), j0 = oe(E0), z0 = V({}, Rl, { data: 0 }), qo = oe(z0), A0 = {
    Esc: "Escape",
    Spacebar: " ",
    Left: "ArrowLeft",
    Up: "ArrowUp",
    Right: "ArrowRight",
    Down: "ArrowDown",
    Del: "Delete",
    Win: "OS",
    Menu: "ContextMenu",
    Apps: "ContextMenu",
    Scroll: "ScrollLock",
    MozPrintableKey: "Unidentified"
  }, O0 = {
    8: "Backspace",
    9: "Tab",
    12: "Clear",
    13: "Enter",
    16: "Shift",
    17: "Control",
    18: "Alt",
    19: "Pause",
    20: "CapsLock",
    27: "Escape",
    32: " ",
    33: "PageUp",
    34: "PageDown",
    35: "End",
    36: "Home",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    45: "Insert",
    46: "Delete",
    112: "F1",
    113: "F2",
    114: "F3",
    115: "F4",
    116: "F5",
    117: "F6",
    118: "F7",
    119: "F8",
    120: "F9",
    121: "F10",
    122: "F11",
    123: "F12",
    144: "NumLock",
    145: "ScrollLock",
    224: "Meta"
  }, M0 = {
    Alt: "altKey",
    Control: "ctrlKey",
    Meta: "metaKey",
    Shift: "shiftKey"
  };
  function C0(t) {
    var e = this.nativeEvent;
    return e.getModifierState ? e.getModifierState(t) : (t = M0[t]) ? !!e[t] : !1;
  }
  function jc() {
    return C0;
  }
  var R0 = V({}, Cn, {
    key: function(t) {
      if (t.key) {
        var e = A0[t.key] || t.key;
        if (e !== "Unidentified") return e;
      }
      return t.type === "keypress" ? (t = Bu(t), t === 13 ? "Enter" : String.fromCharCode(t)) : t.type === "keydown" || t.type === "keyup" ? O0[t.keyCode] || "Unidentified" : "";
    },
    code: 0,
    location: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    repeat: 0,
    locale: 0,
    getModifierState: jc,
    charCode: function(t) {
      return t.type === "keypress" ? Bu(t) : 0;
    },
    keyCode: function(t) {
      return t.type === "keydown" || t.type === "keyup" ? t.keyCode : 0;
    },
    which: function(t) {
      return t.type === "keypress" ? Bu(t) : t.type === "keydown" || t.type === "keyup" ? t.keyCode : 0;
    }
  }), D0 = oe(R0), U0 = V({}, Lu, {
    pointerId: 0,
    width: 0,
    height: 0,
    pressure: 0,
    tangentialPressure: 0,
    tiltX: 0,
    tiltY: 0,
    twist: 0,
    pointerType: 0,
    isPrimary: 0
  }), Yo = oe(U0), w0 = V({}, Rl, { submitter: 0 }), H0 = oe(w0), B0 = V({}, Cn, {
    touches: 0,
    targetTouches: 0,
    changedTouches: 0,
    altKey: 0,
    metaKey: 0,
    ctrlKey: 0,
    shiftKey: 0,
    getModifierState: jc
  }), q0 = oe(B0), Y0 = V({}, Rl, {
    propertyName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), L0 = oe(Y0), X0 = V({}, Lu, {
    deltaX: function(t) {
      return "deltaX" in t ? t.deltaX : "wheelDeltaX" in t ? -t.wheelDeltaX : 0;
    },
    deltaY: function(t) {
      return "deltaY" in t ? t.deltaY : "wheelDeltaY" in t ? -t.wheelDeltaY : "wheelDelta" in t ? -t.wheelDelta : 0;
    },
    deltaZ: 0,
    deltaMode: 0
  }), G0 = oe(X0), Q0 = V({}, Rl, {
    newState: 0,
    oldState: 0,
    source: 0
  }), V0 = oe(Q0), Z0 = [9, 13, 27, 32], zc = yl && "CompositionEvent" in window, Dn = null;
  yl && "documentMode" in document && (Dn = document.documentMode);
  var K0 = yl && "TextEvent" in window && !Dn, Lo = yl && (!zc || Dn && 8 < Dn && 11 >= Dn), Xo = " ", Go = !1;
  function Qo(t, e) {
    switch (t) {
      case "keyup":
        return Z0.indexOf(e.keyCode) !== -1;
      case "keydown":
        return e.keyCode !== 229;
      case "keypress":
      case "mousedown":
      case "focusout":
        return !0;
      default:
        return !1;
    }
  }
  function Vo(t) {
    return t = t.detail, typeof t == "object" && "data" in t ? t.data : null;
  }
  var Ba = !1;
  function k0(t, e) {
    switch (t) {
      case "compositionend":
        return Vo(e);
      case "keypress":
        return e.which !== 32 ? null : (Go = !0, Xo);
      case "textInput":
        return t = e.data, t === Xo && Go ? null : t;
      default:
        return null;
    }
  }
  function J0(t, e) {
    if (Ba)
      return t === "compositionend" || !zc && Qo(t, e) ? (t = wo(), Hu = _c = Cl = null, Ba = !1, t) : null;
    switch (t) {
      case "paste":
        return null;
      case "keypress":
        if (!(e.ctrlKey || e.altKey || e.metaKey) || e.ctrlKey && e.altKey) {
          if (e.char && 1 < e.char.length)
            return e.char;
          if (e.which) return String.fromCharCode(e.which);
        }
        return null;
      case "compositionend":
        return Lo && e.locale !== "ko" ? null : e.data;
      default:
        return null;
    }
  }
  var $0 = {
    color: !0,
    date: !0,
    datetime: !0,
    "datetime-local": !0,
    email: !0,
    month: !0,
    number: !0,
    password: !0,
    range: !0,
    search: !0,
    tel: !0,
    text: !0,
    time: !0,
    url: !0,
    week: !0
  };
  function Zo(t) {
    var e = t && t.nodeName && t.nodeName.toLowerCase();
    return e === "input" ? !!$0[t.type] : e === "textarea";
  }
  function Ko(t, e, l, a) {
    wa ? Ha ? Ha.push(a) : Ha = [a] : wa = a, e = Xi(e, "onChange"), 0 < e.length && (l = new Yu(
      "onChange",
      "change",
      null,
      l,
      a
    ), t.push({ event: l, listeners: e }));
  }
  var Un = null, wn = null;
  function F0(t) {
    Dm(t, 0);
  }
  function Xu(t) {
    var e = An(t);
    if (zo(e)) return t;
  }
  function ko(t, e) {
    if (t === "change") return e;
  }
  var Jo = !1;
  if (yl) {
    var Ac;
    if (yl) {
      var Oc = "oninput" in document;
      if (!Oc) {
        var $o = document.createElement("div");
        $o.setAttribute("oninput", "return;"), Oc = typeof $o.oninput == "function";
      }
      Ac = Oc;
    } else Ac = !1;
    Jo = Ac && (!document.documentMode || 9 < document.documentMode);
  }
  function Fo() {
    Un && (Un.detachEvent("onpropertychange", Wo), wn = Un = null);
  }
  function Wo(t) {
    if (t.propertyName === "value" && Xu(wn)) {
      var e = [];
      Ko(
        e,
        wn,
        t,
        bc(t)
      ), Uo(F0, e);
    }
  }
  function W0(t, e, l) {
    t === "focusin" ? (Fo(), Un = e, wn = l, Un.attachEvent("onpropertychange", Wo)) : t === "focusout" && Fo();
  }
  function I0(t) {
    if (t === "selectionchange" || t === "keyup" || t === "keydown")
      return Xu(wn);
  }
  function P0(t, e) {
    if (t === "click") return Xu(e);
  }
  function ty(t, e) {
    if (t === "input" || t === "change")
      return Xu(e);
  }
  function ey(t, e) {
    return t === e && (t !== 0 || 1 / t === 1 / e) || t !== t && e !== e;
  }
  var je = typeof Object.is == "function" ? Object.is : ey;
  function Hn(t, e) {
    if (je(t, e)) return !0;
    if (typeof t != "object" || t === null || typeof e != "object" || e === null)
      return !1;
    var l = Object.keys(t), a = Object.keys(e);
    if (l.length !== a.length) return !1;
    for (a = 0; a < l.length; a++) {
      var n = l[a];
      if (!sc.call(e, n) || !je(t[n], e[n]))
        return !1;
    }
    return !0;
  }
  function Mc(t) {
    if (t = t || (typeof document < "u" ? document : void 0), typeof t > "u") return null;
    try {
      return t.activeElement || t.body;
    } catch {
      return t.body;
    }
  }
  function Io(t) {
    for (; t && t.firstChild; ) t = t.firstChild;
    return t;
  }
  function Po(t, e) {
    var l = Io(t);
    t = 0;
    for (var a; l; ) {
      if (l.nodeType === 3) {
        if (a = t + l.textContent.length, t <= e && a >= e)
          return { node: l, offset: e - t };
        t = a;
      }
      t: {
        for (; l; ) {
          if (l.nextSibling) {
            l = l.nextSibling;
            break t;
          }
          l = l.parentNode;
        }
        l = void 0;
      }
      l = Io(l);
    }
  }
  function tr(t, e) {
    return t && e ? t === e ? !0 : t && t.nodeType === 3 ? !1 : e && e.nodeType === 3 ? tr(t, e.parentNode) : "contains" in t ? t.contains(e) : t.compareDocumentPosition ? !!(t.compareDocumentPosition(e) & 16) : !1 : !1;
  }
  function er(t) {
    t = t != null && t.ownerDocument != null && t.ownerDocument.defaultView != null ? t.ownerDocument.defaultView : window;
    for (var e = Mc(t.document); e instanceof t.HTMLIFrameElement; ) {
      try {
        var l = typeof e.contentWindow.location.href == "string";
      } catch {
        l = !1;
      }
      if (l) t = e.contentWindow;
      else break;
      e = Mc(t.document);
    }
    return e;
  }
  function Cc(t) {
    var e = t && t.nodeName && t.nodeName.toLowerCase();
    return e && (e === "input" && (t.type === "text" || t.type === "search" || t.type === "tel" || t.type === "url" || t.type === "password") || e === "textarea" || t.contentEditable === "true");
  }
  var ly = yl && "documentMode" in document && 11 >= document.documentMode, qa = null, Rc = null, Bn = null, Dc = !1;
  function lr(t, e, l) {
    var a = l.window === l ? l.document : l.nodeType === 9 ? l : l.ownerDocument;
    Dc || qa == null || qa !== Mc(a) || (a = qa, "selectionStart" in a && Cc(a) ? a = { start: a.selectionStart, end: a.selectionEnd } : (a = (a.ownerDocument && a.ownerDocument.defaultView || window).getSelection(), a = {
      anchorNode: a.anchorNode,
      anchorOffset: a.anchorOffset,
      focusNode: a.focusNode,
      focusOffset: a.focusOffset
    }), Bn && Hn(Bn, a) || (Bn = a, a = Xi(Rc, "onSelect"), 0 < a.length && (e = new Yu(
      "onSelect",
      "select",
      null,
      e,
      l
    ), t.push({ event: e, listeners: a }), e.target = qa)));
  }
  function ca(t, e) {
    var l = {};
    return l[t.toLowerCase()] = e.toLowerCase(), l["Webkit" + t] = "webkit" + e, l["Moz" + t] = "moz" + e, l;
  }
  var Ya = {
    animationend: ca("Animation", "AnimationEnd"),
    animationiteration: ca("Animation", "AnimationIteration"),
    animationstart: ca("Animation", "AnimationStart"),
    transitionrun: ca("Transition", "TransitionRun"),
    transitionstart: ca("Transition", "TransitionStart"),
    transitioncancel: ca("Transition", "TransitionCancel"),
    transitionend: ca("Transition", "TransitionEnd")
  }, Uc = {}, ar = {};
  yl && (ar = document.createElement("div").style, "AnimationEvent" in window || (delete Ya.animationend.animation, delete Ya.animationiteration.animation, delete Ya.animationstart.animation), "TransitionEvent" in window || delete Ya.transitionend.transition);
  function sa(t) {
    if (Uc[t]) return Uc[t];
    if (!Ya[t]) return t;
    var e = Ya[t], l;
    for (l in e)
      if (e.hasOwnProperty(l) && l in ar)
        return Uc[t] = e[l];
    return t;
  }
  var nr = sa("animationend"), ur = sa("animationiteration"), ir = sa("animationstart"), ay = sa("transitionrun"), ny = sa("transitionstart"), uy = sa("transitioncancel"), cr = sa("transitionend"), sr = /* @__PURE__ */ new Map(), wc = "abort auxClick beforeToggle cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error fullscreenChange fullscreenError gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(
    " "
  );
  wc.push("scrollEnd");
  function ke(t, e) {
    sr.set(t, e), ia(e, [t]);
  }
  var iy = 0;
  function vl(t, e) {
    if (t.name != null && t.name !== "auto") return t.name;
    if (e.autoName !== null) return e.autoName;
    t = We.identifierPrefix;
    var l = iy++;
    return t = "_" + t + "t_" + l.toString(32) + "_", e.autoName = t;
  }
  function fr(t) {
    if (t == null || typeof t == "string")
      return t;
    var e = null, l = un;
    if (l !== null)
      for (var a = 0; a < l.length; a++) {
        var n = t[l[a]];
        if (n != null) {
          if (n === "none") return "none";
          e = e == null ? n : e + (" " + n);
        }
      }
    return e ?? t.default;
  }
  function gl(t, e) {
    return t = fr(t), e = fr(e), e == null ? t === "auto" ? null : t : e === "auto" ? null : e;
  }
  var Gu = typeof reportError == "function" ? reportError : function(t) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var e = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof t == "object" && t !== null && typeof t.message == "string" ? String(t.message) : String(t),
        error: t
      });
      if (!window.dispatchEvent(e)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", t);
      return;
    }
    console.error(t);
  }, Be = [], La = 0, Hc = 0;
  function Qu() {
    for (var t = La, e = Hc = La = 0; e < t; ) {
      var l = Be[e];
      Be[e++] = null;
      var a = Be[e];
      Be[e++] = null;
      var n = Be[e];
      Be[e++] = null;
      var u = Be[e];
      if (Be[e++] = null, a !== null && n !== null) {
        var i = a.pending;
        i === null ? n.next = n : (n.next = i.next, i.next = n), a.pending = n;
      }
      u !== 0 && or(l, n, u);
    }
  }
  function Vu(t, e, l, a) {
    Be[La++] = t, Be[La++] = e, Be[La++] = l, Be[La++] = a, Hc |= a, t.lanes |= a, t = t.alternate, t !== null && (t.lanes |= a);
  }
  function Bc(t, e, l, a) {
    return Vu(t, e, l, a), Zu(t);
  }
  function fa(t, e) {
    return Vu(t, null, null, e), Zu(t);
  }
  function or(t, e, l) {
    t.lanes |= l;
    var a = t.alternate;
    a !== null && (a.lanes |= l);
    for (var n = !1, u = t.return; u !== null; )
      u.childLanes |= l, a = u.alternate, a !== null && (a.childLanes |= l), u.tag === 22 && (t = u.stateNode, t === null || t._visibility & 1 || (n = !0)), t = u, u = u.return;
    return t.tag === 3 ? (u = t.stateNode, n && e !== null && (n = 31 - Te(l), t = u.hiddenUpdates, a = t[n], a === null ? t[n] = [e] : a.push(e), e.lane = l | 536870912), u) : null;
  }
  function Zu(t) {
    if (50 < uu)
      throw uu = 0, Ui = null, Error(o(185));
    for (var e = t.return; e !== null; )
      t = e, e = t.return;
    return t.tag === 3 ? t.stateNode : null;
  }
  var Xa = {};
  function cy(t, e, l, a) {
    this.tag = t, this.key = l, this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null, this.index = 0, this.refCleanup = this.ref = null, this.pendingProps = e, this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null, this.mode = a, this.subtreeFlags = this.flags = 0, this.deletions = null, this.childLanes = this.lanes = 0, this.alternate = null;
  }
  function ve(t, e, l, a) {
    return new cy(t, e, l, a);
  }
  function qc(t) {
    return t = t.prototype, !(!t || !t.isReactComponent);
  }
  function pl(t, e) {
    var l = t.alternate;
    return l === null ? (l = ve(
      t.tag,
      e,
      t.key,
      t.mode
    ), l.elementType = t.elementType, l.type = t.type, l.stateNode = t.stateNode, l.alternate = t, t.alternate = l) : (l.pendingProps = e, l.type = t.type, l.flags = 0, l.subtreeFlags = 0, l.deletions = null), l.flags = t.flags & 1206910976, l.childLanes = t.childLanes, l.lanes = t.lanes, l.child = t.child, l.memoizedProps = t.memoizedProps, l.memoizedState = t.memoizedState, l.updateQueue = t.updateQueue, e = t.dependencies, l.dependencies = e === null ? null : { lanes: e.lanes, firstContext: e.firstContext }, l.sibling = t.sibling, l.index = t.index, l.ref = t.ref, l.refCleanup = t.refCleanup, l;
  }
  function rr(t, e) {
    t.flags &= 1206910978;
    var l = t.alternate;
    return l === null ? (t.childLanes = 0, t.lanes = e, t.child = null, t.subtreeFlags = 0, t.memoizedProps = null, t.memoizedState = null, t.updateQueue = null, t.dependencies = null, t.stateNode = null) : (t.childLanes = l.childLanes, t.lanes = l.lanes, t.child = l.child, t.subtreeFlags = 0, t.deletions = null, t.memoizedProps = l.memoizedProps, t.memoizedState = l.memoizedState, t.updateQueue = l.updateQueue, t.type = l.type, e = l.dependencies, t.dependencies = e === null ? null : {
      lanes: e.lanes,
      firstContext: e.firstContext
    }), t;
  }
  function Ku(t, e, l, a, n, u) {
    var i = 0;
    if (a = t, typeof a == "function") qc(a) && (i = 1);
    else if (typeof a == "string")
      i = wv(
        t,
        l,
        Pe.current
      ) ? 26 : t === "html" || t === "head" || t === "body" ? 27 : 5;
    else
      t: switch (a) {
        case ee:
          return t = ve(31, l, e, n), t.elementType = ee, t.lanes = u, t;
        case Yt:
          return oa(l.children, n, u, e);
        case Lt:
          i = 8, n |= 24;
          break;
        case Ht:
          return t = ve(12, l, e, n | 2), t.elementType = Ht, t.lanes = u, t;
        case P:
          return t = ve(13, l, e, n), t.elementType = P, t.lanes = u, t;
        case I:
          return t = ve(19, l, e, n), t.elementType = I, t.lanes = u, t;
        case Se:
        case d:
          return t = n | 32, t = ve(30, l, e, t), t.elementType = d, t.lanes = u, t.stateNode = {
            autoName: null,
            paired: null,
            clones: null,
            ref: null
          }, t;
        default:
          if (typeof a == "object" && a !== null)
            switch (a.$$typeof) {
              case Rt:
                i = 10;
                break t;
              case $t:
                i = 9;
                break t;
              case X:
                i = 11;
                break t;
              case pt:
                i = 14;
                break t;
              case st:
                i = 16, a = null;
                break t;
            }
          i = 29, l = Error(
            o(130, t === null ? "null" : typeof t, "")
          ), a = null;
      }
    return e = ve(i, l, e, n), e.elementType = t, e.type = a, e.lanes = u, e;
  }
  function oa(t, e, l, a) {
    return t = ve(7, t, a, e), t.lanes = l, t;
  }
  function Yc(t, e, l) {
    return t = ve(6, t, null, e), t.lanes = l, t;
  }
  function dr(t) {
    var e = ve(18, null, null, 0);
    return e.stateNode = t, e;
  }
  function Lc(t, e, l) {
    return e = ve(
      4,
      t.children !== null ? t.children : [],
      t.key,
      e
    ), e.lanes = l, e.stateNode = {
      containerInfo: t.containerInfo,
      pendingChildren: null,
      implementation: t.implementation
    }, e;
  }
  var mr = /* @__PURE__ */ new WeakMap();
  function qe(t, e) {
    if (typeof t == "object" && t !== null) {
      var l = mr.get(t);
      return l !== void 0 ? l : (e = {
        value: t,
        source: e,
        stack: io(e)
      }, mr.set(t, e), e);
    }
    return {
      value: t,
      source: e,
      stack: io(e)
    };
  }
  var Ga = [], Qa = 0, ku = null, qn = 0, Ye = [], Le = 0, Dl = null, el = 1, ll = "";
  function bl(t, e) {
    Ga[Qa++] = qn, Ga[Qa++] = ku, ku = t, qn = e;
  }
  function hr(t, e, l) {
    Ye[Le++] = el, Ye[Le++] = ll, Ye[Le++] = Dl, Dl = t;
    var a = el;
    t = ll;
    var n = 32 - Te(a) - 1;
    a &= ~(1 << n), l += 1;
    var u = 32 - Te(e) + n;
    if (30 < u) {
      var i = n - n % 5;
      u = (a & (1 << i) - 1).toString(32), a >>= i, n -= i, el = 1 << 32 - Te(e) + n | l << n | a, ll = u + t;
    } else
      el = 1 << u | l << n | a, ll = t;
  }
  function Ju(t) {
    t.return !== null && (bl(t, 1), hr(t, 1, 0));
  }
  function Xc(t) {
    for (; t === ku; )
      ku = Ga[--Qa], Ga[Qa] = null, qn = Ga[--Qa], Ga[Qa] = null;
    for (; t === Dl; )
      Dl = Ye[--Le], Ye[Le] = null, ll = Ye[--Le], Ye[Le] = null, el = Ye[--Le], Ye[Le] = null;
  }
  function yr(t, e) {
    Ye[Le++] = el, Ye[Le++] = ll, Ye[Le++] = Dl, el = e.id, ll = e.overflow, Dl = t;
  }
  var It = null, Mt = null, ot = !1, Ul = null, Xe = !1, Gc = Error(o(519));
  function wl(t) {
    var e = Error(
      o(
        418,
        1 < arguments.length && arguments[1] !== void 0 && arguments[1] ? "text" : "HTML",
        ""
      )
    );
    throw Yn(qe(e, t)), Gc;
  }
  function vr(t) {
    var e = t.stateNode, l = t.type, a = t.memoizedProps;
    switch (e[le] = t, e[ye] = a, l) {
      case "dialog":
        ht("cancel", e), ht("close", e);
        break;
      case "iframe":
      case "object":
      case "embed":
        ht("load", e);
        break;
      case "video":
      case "audio":
        for (l = 0; l < cu.length; l++)
          ht(cu[l], e);
        break;
      case "source":
        ht("error", e);
        break;
      case "img":
      case "image":
      case "link":
        ht("error", e), ht("load", e);
        break;
      case "details":
        ht("toggle", e);
        break;
      case "input":
        ht("invalid", e), Ao(
          e,
          a.value,
          a.defaultValue,
          a.checked,
          a.defaultChecked,
          a.type,
          a.name,
          !0
        );
        break;
      case "select":
        ht("invalid", e);
        break;
      case "textarea":
        ht("invalid", e), Mo(e, a.value, a.defaultValue, a.children);
    }
    l = a.children, typeof l != "string" && typeof l != "number" && typeof l != "bigint" || e.textContent === "" + l || a.suppressHydrationWarning === !0 || Bm(e.textContent, l) ? (a.popover != null && (ht("beforetoggle", e), ht("toggle", e)), a.onScroll != null && ht("scroll", e), a.onScrollEnd != null && ht("scrollend", e), a.onClick != null && (e.onclick = tl), e = !0) : e = !1, e || wl(t, !0);
  }
  function $u(t) {
    for (It = t.return; It; )
      switch (It.tag) {
        case 5:
        case 31:
        case 13:
          Xe = !1;
          return;
        case 27:
        case 3:
          Xe = !0;
          return;
        default:
          It = It.return;
      }
  }
  function Va(t) {
    if (t !== It) return !1;
    if (!ot) return $u(t), ot = !0, !1;
    var e = t.tag, l;
    if ((l = e !== 3 && e !== 27) && ((l = e === 5) && (l = t.type, l = !(l !== "form" && l !== "button") || bf(t.type, t.memoizedProps)), l = !l), l && Mt && wl(t), $u(t), e === 13) {
      if (t = t.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(o(317));
      Mt = lh(t);
    } else if (e === 31) {
      if (t = t.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(o(317));
      Mt = lh(t);
    } else
      e === 27 ? (e = Mt, Wl(t.type) ? (t = Af, Af = null, Mt = t) : Mt = e) : Mt = It ? Qe(t.stateNode.nextSibling) : null;
    return !0;
  }
  function ra() {
    Mt = It = null, ot = !1;
  }
  function Qc() {
    var t = Ul;
    return t !== null && (be === null ? be = t : be.push.apply(
      be,
      t
    ), Ul = null), t;
  }
  function Yn(t) {
    Ul === null ? Ul = [t] : Ul.push(t);
  }
  var Vc = we(null), da = null, xl = null;
  function Hl(t, e, l) {
    Ot(Vc, e._currentValue), e._currentValue = l;
  }
  function Sl(t) {
    t._currentValue = Vc.current, Qt(Vc);
  }
  function Fu(t, e, l) {
    for (; t !== null; ) {
      var a = t.alternate;
      if ((t.childLanes & e) !== e ? (t.childLanes |= e, a !== null && (a.childLanes |= e)) : a !== null && (a.childLanes & e) !== e && (a.childLanes |= e), t === l) break;
      t = t.return;
    }
  }
  function Zc(t, e, l, a) {
    var n = t.child;
    for (n !== null && (n.return = t); n !== null; ) {
      var u = n.dependencies;
      if (u !== null) {
        var i = n.child;
        u = u.firstContext;
        t: for (; u !== null; ) {
          var f = u;
          u = n;
          for (var m = 0; m < e.length; m++)
            if (f.context === e[m]) {
              u.lanes |= l, f = u.alternate, f !== null && (f.lanes |= l), Fu(
                u.return,
                l,
                t
              ), a || (i = null);
              break t;
            }
          u = f.next;
        }
      } else if (n.tag === 18) {
        if (i = n.return, i === null) throw Error(o(341));
        i.lanes |= l, u = i.alternate, u !== null && (u.lanes |= l), Fu(i, l, t), i = null;
      } else
        n.tag === 13 && n.memoizedState !== null && n.memoizedState.dehydrated === null ? (n.lanes |= l, i = n.alternate, i !== null && (i.lanes |= l), Fu(
          n.return,
          l,
          t
        ), i = n.child, i = i !== null ? i.sibling : null) : i = n.child;
      if (i !== null) i.return = n;
      else
        for (i = n; i !== null; ) {
          if (i === t) {
            i = null;
            break;
          }
          if (n = i.sibling, n !== null) {
            n.return = i.return, i = n;
            break;
          }
          i = i.return;
        }
      n = i;
    }
  }
  function ma(t, e, l, a) {
    t = null;
    for (var n = e, u = !1; n !== null; ) {
      if (!u) {
        if ((n.flags & 524288) !== 0) u = !0;
        else if ((n.flags & 262144) !== 0) break;
      }
      if (n.tag === 10) {
        var i = n.alternate;
        if (i === null) throw Error(o(387));
        if (i = i.memoizedProps, i !== null) {
          var f = n.type;
          je(n.pendingProps.value, i.value) || (t !== null ? t.push(f) : t = [f]);
        }
      } else if (n === Nu.current) {
        if (i = n.alternate, i === null) throw Error(o(387));
        i.memoizedState.memoizedState !== n.memoizedState.memoizedState && (t !== null ? t.push(vn) : t = [vn]);
      }
      n = n.return;
    }
    return t !== null && Zc(
      e,
      t,
      l,
      a
    ), e.flags |= 262144, t !== null;
  }
  function Wu(t) {
    for (t = t.firstContext; t !== null; ) {
      if (!je(
        t.context._currentValue,
        t.memoizedValue
      ))
        return !0;
      t = t.next;
    }
    return !1;
  }
  function ha(t) {
    da = t, xl = null, t = t.dependencies, t !== null && (t.firstContext = null);
  }
  function ae(t) {
    return gr(da, t);
  }
  function Iu(t, e) {
    return da === null && ha(t), gr(t, e);
  }
  function gr(t, e) {
    var l = e._currentValue;
    if (e = { context: e, memoizedValue: l, next: null }, xl === null) {
      if (t === null) throw Error(o(308));
      xl = e, t.dependencies = { lanes: 0, firstContext: e }, t.flags |= 524288;
    } else xl = xl.next = e;
    return l;
  }
  var sy = typeof AbortController < "u" ? AbortController : function() {
    var t = [], e = this.signal = {
      aborted: !1,
      addEventListener: function(l, a) {
        t.push(a);
      }
    };
    this.abort = function() {
      e.aborted = !0, t.forEach(function(l) {
        return l();
      });
    };
  }, fy = c.unstable_scheduleCallback, oy = c.unstable_NormalPriority, Zt = {
    $$typeof: Rt,
    Consumer: null,
    Provider: null,
    _currentValue: null,
    _currentValue2: null,
    _threadCount: 0
  };
  function Kc() {
    return {
      controller: new sy(),
      data: /* @__PURE__ */ new Map(),
      refCount: 0
    };
  }
  function Ln(t) {
    t.refCount--, t.refCount === 0 && fy(oy, function() {
      t.controller.abort();
    });
  }
  function pr(t, e) {
    if ((t.pendingLanes & 4194048) !== 0) {
      var l = t.transitionTypes;
      for (l === null && (l = t.transitionTypes = []), t = 0; t < e.length; t++) {
        var a = e[t];
        l.indexOf(a) === -1 && l.push(a);
      }
    }
  }
  var Xn = null;
  function ry(t) {
    var e = t.transitionTypes;
    return t.transitionTypes = null, e;
  }
  var Gn = null, kc = 0, ya = 0, Za = null;
  function dy(t, e) {
    if (Gn === null) {
      var l = Gn = [];
      kc = 0, ya = of(), Za = {
        status: "pending",
        value: void 0,
        then: function(a) {
          l.push(a);
        }
      };
    }
    return kc++, e.then(br, br), e;
  }
  function br() {
    if (--kc === 0 && (Xn = null, Gn !== null)) {
      Za !== null && (Za.status = "fulfilled");
      var t = Gn;
      Gn = null, ya = 0, Za = null;
      for (var e = 0; e < t.length; e++) (0, t[e])();
    }
  }
  function my(t, e) {
    var l = [], a = {
      status: "pending",
      value: null,
      reason: null,
      then: function(n) {
        l.push(n);
      }
    };
    return t.then(
      function() {
        a.status = "fulfilled", a.value = e;
        for (var n = 0; n < l.length; n++) (0, l[n])(e);
      },
      function(n) {
        for (a.status = "rejected", a.reason = n, n = 0; n < l.length; n++)
          (0, l[n])(void 0);
      }
    ), a;
  }
  var xr = G.S;
  G.S = function(t, e) {
    if (dm = _e(), typeof e == "object" && e !== null && typeof e.then == "function" && dy(t, e), Xn !== null)
      for (var l = on; l !== null; )
        pr(l, Xn), l = l.next;
    if (l = t.types, l !== null) {
      for (var a = on; a !== null; )
        pr(a, l), a = a.next;
      if (ya !== 0) {
        a = Xn, a === null && (a = Xn = []);
        for (var n = 0; n < l.length; n++) {
          var u = l[n];
          a.indexOf(u) === -1 && a.push(u);
        }
      }
    }
    xr !== null && xr(t, e);
  };
  var va = we(null);
  function Jc() {
    var t = va.current;
    return t !== null ? t : At.pooledCache;
  }
  function Pu(t, e) {
    e === null ? Ot(va, va.current) : Ot(va, e.pool);
  }
  function Sr() {
    var t = Jc();
    return t === null ? null : { parent: Zt._currentValue, pool: t };
  }
  var Ka = Error(o(460)), $c = Error(o(474)), ti = Error(o(542)), ei = { then: function() {
  } };
  function _r(t) {
    return t = t.status, t === "fulfilled" || t === "rejected";
  }
  function Nr(t, e, l) {
    switch (l = t[l], l === void 0 ? t.push(e) : l !== e && (e.then(tl, tl), e = l), e.status) {
      case "fulfilled":
        return e.value;
      case "rejected":
        throw t = e.reason, Er(t), t === void 0 && !("reason" in e) ? Error(o(600)) : t;
      default:
        if (typeof e.status == "string") e.then(tl, tl);
        else {
          if (t = At, t !== null && 100 < t.shellSuspendCounter)
            throw Error(o(482));
          t = e, t.status = "pending", t.then(
            function(a) {
              if (e.status === "pending") {
                var n = e;
                n.status = "fulfilled", n.value = a;
              }
            },
            function(a) {
              if (e.status === "pending") {
                var n = e;
                n.status = "rejected", n.reason = a;
              }
            }
          );
        }
        switch (e.status) {
          case "fulfilled":
            return e.value;
          case "rejected":
            throw t = e.reason, Er(t), t;
        }
        throw pa = e, Ka;
    }
  }
  function ga(t) {
    try {
      var e = t._init;
      return e(t._payload);
    } catch (l) {
      throw l !== null && typeof l == "object" && typeof l.then == "function" ? (pa = l, Ka) : l;
    }
  }
  var pa = null;
  function Tr() {
    if (pa === null) throw Error(o(459));
    var t = pa;
    return pa = null, t;
  }
  function Er(t) {
    if (t === Ka || t === ti)
      throw Error(o(483));
  }
  var ka = null, Qn = 0;
  function li(t) {
    var e = Qn;
    return Qn += 1, ka === null && (ka = []), Nr(ka, t, e);
  }
  function Bl(t, e) {
    e = e.props.ref, t.ref = e !== void 0 ? e : null;
  }
  function ai(t, e) {
    throw e.$$typeof === k ? Error(o(525)) : (t = Object.prototype.toString.call(e), Error(
      o(
        31,
        t === "[object Object]" ? "object with keys {" + Object.keys(e).join(", ") + "}" : t
      )
    ));
  }
  function jr(t) {
    function e(b, v) {
      if (t) {
        var S = b.deletions;
        S === null ? (b.deletions = [v], b.flags |= 16) : S.push(v);
      }
    }
    function l(b, v) {
      if (!t) return null;
      for (; v !== null; )
        e(b, v), v = v.sibling;
      return null;
    }
    function a(b) {
      for (var v = /* @__PURE__ */ new Map(); b !== null; )
        b.key === null ? v.set(b.index, b) : v.set(b.key, b), b = b.sibling;
      return v;
    }
    function n(b, v) {
      return b = pl(b, v), b.index = 0, b.sibling = null, b;
    }
    function u(b, v, S) {
      return b.index = S, t ? (S = b.alternate, S !== null ? (S = S.index, S < v ? (b.flags |= 2, v) : S) : (b.flags |= 134217730, v)) : (b.flags |= 1048576, v);
    }
    function i(b) {
      return t && b.alternate === null && (b.flags |= 134217730), b;
    }
    function f(b, v, S, O) {
      return v === null || v.tag !== 6 ? (v = Yc(S, b.mode, O), v.return = b, v) : (v = n(v, S), v.return = b, v);
    }
    function m(b, v, S, O) {
      var Z = S.type;
      return Z === Yt ? (b = j(
        b,
        v,
        S.props.children,
        O,
        S.key
      ), Bl(b, S), b) : v !== null && (v.elementType === Z || typeof Z == "object" && Z !== null && Z.$$typeof === st && ga(Z) === v.type) ? (v = n(v, S.props), Bl(v, S), v.return = b, v) : (v = Ku(
        S.type,
        S.key,
        S.props,
        null,
        b.mode,
        O
      ), Bl(v, S), v.return = b, v);
    }
    function x(b, v, S, O) {
      return v === null || v.tag !== 4 || v.stateNode.containerInfo !== S.containerInfo || v.stateNode.implementation !== S.implementation ? (v = Lc(S, b.mode, O), v.return = b, v) : (v = n(v, S.children || []), v.return = b, v);
    }
    function j(b, v, S, O, Z) {
      return v === null || v.tag !== 7 ? (v = oa(
        S,
        b.mode,
        O,
        Z
      ), v.return = b, v) : (v = n(v, S), v.return = b, v);
    }
    function C(b, v, S) {
      if (typeof v == "string" && v !== "" || typeof v == "number" || typeof v == "bigint")
        return v = Yc(
          "" + v,
          b.mode,
          S
        ), v.return = b, v;
      if (typeof v == "object" && v !== null) {
        switch (v.$$typeof) {
          case qt:
            return S = Ku(
              v.type,
              v.key,
              v.props,
              null,
              b.mode,
              S
            ), Bl(S, v), S.return = b, S;
          case xt:
            return v = Lc(
              v,
              b.mode,
              S
            ), v.return = b, v;
          case st:
            return v = ga(v), C(b, v, S);
        }
        if (et(v) || U(v))
          return v = oa(
            v,
            b.mode,
            S,
            null
          ), v.return = b, v;
        if (typeof v.then == "function")
          return C(b, li(v), S);
        if (v.$$typeof === Rt)
          return C(
            b,
            Iu(b, v),
            S
          );
        ai(b, v);
      }
      return null;
    }
    function g(b, v, S, O) {
      var Z = v !== null ? v.key : null;
      if (typeof S == "string" && S !== "" || typeof S == "number" || typeof S == "bigint")
        return Z !== null ? null : f(b, v, "" + S, O);
      if (typeof S == "object" && S !== null) {
        switch (S.$$typeof) {
          case qt:
            return S.key === Z ? m(b, v, S, O) : null;
          case xt:
            return S.key === Z ? x(b, v, S, O) : null;
          case st:
            return S = ga(S), g(b, v, S, O);
        }
        if (et(S) || U(S))
          return Z !== null ? null : j(b, v, S, O, null);
        if (typeof S.then == "function")
          return g(
            b,
            v,
            li(S),
            O
          );
        if (S.$$typeof === Rt)
          return g(
            b,
            v,
            Iu(b, S),
            O
          );
        ai(b, S);
      }
      return null;
    }
    function T(b, v, S, O, Z) {
      if (typeof O == "string" && O !== "" || typeof O == "number" || typeof O == "bigint")
        return b = b.get(S) || null, f(v, b, "" + O, Z);
      if (typeof O == "object" && O !== null) {
        switch (O.$$typeof) {
          case qt:
            return b = b.get(
              O.key === null ? S : O.key
            ) || null, m(v, b, O, Z);
          case xt:
            return b = b.get(
              O.key === null ? S : O.key
            ) || null, x(v, b, O, Z);
          case st:
            return O = ga(O), T(
              b,
              v,
              S,
              O,
              Z
            );
        }
        if (et(O) || U(O))
          return b = b.get(S) || null, j(v, b, O, Z, null);
        if (typeof O.then == "function")
          return T(
            b,
            v,
            S,
            li(O),
            Z
          );
        if (O.$$typeof === Rt)
          return T(
            b,
            v,
            S,
            Iu(v, O),
            Z
          );
        ai(v, O);
      }
      return null;
    }
    function L(b, v, S, O) {
      for (var Z = null, vt = null, tt = v, lt = v = 0, Jt = null; tt !== null && lt < S.length; lt++) {
        tt.index > lt ? (Jt = tt, tt = null) : Jt = tt.sibling;
        var gt = g(
          b,
          tt,
          S[lt],
          O
        );
        if (gt === null) {
          tt === null && (tt = Jt);
          break;
        }
        t && tt && gt.alternate === null && e(b, tt), v = u(gt, v, lt), vt === null ? Z = gt : vt.sibling = gt, vt = gt, tt = Jt;
      }
      if (lt === S.length)
        return l(b, tt), ot && bl(b, lt), Z;
      if (tt === null) {
        for (; lt < S.length; lt++)
          tt = C(b, S[lt], O), tt !== null && (v = u(
            tt,
            v,
            lt
          ), vt === null ? Z = tt : vt.sibling = tt, vt = tt);
        return ot && bl(b, lt), Z;
      }
      for (tt = a(tt); lt < S.length; lt++)
        Jt = T(
          tt,
          b,
          lt,
          S[lt],
          O
        ), Jt !== null && (t && (gt = Jt.alternate, gt !== null && tt.delete(gt.key === null ? lt : gt.key)), v = u(
          Jt,
          v,
          lt
        ), vt === null ? Z = Jt : vt.sibling = Jt, vt = Jt);
      return t && tt.forEach(function(la) {
        return e(b, la);
      }), ot && bl(b, lt), Z;
    }
    function $(b, v, S, O) {
      if (S == null) throw Error(o(151));
      for (var Z = null, vt = null, tt = v, lt = v = 0, Jt = null, gt = S.next(); tt !== null && !gt.done; lt++, gt = S.next()) {
        tt.index > lt ? (Jt = tt, tt = null) : Jt = tt.sibling;
        var la = g(b, tt, gt.value, O);
        if (la === null) {
          tt === null && (tt = Jt);
          break;
        }
        t && tt && la.alternate === null && e(b, tt), v = u(la, v, lt), vt === null ? Z = la : vt.sibling = la, vt = la, tt = Jt;
      }
      if (gt.done)
        return l(b, tt), ot && bl(b, lt), Z;
      if (tt === null) {
        for (; !gt.done; lt++, gt = S.next())
          gt = C(b, gt.value, O), gt !== null && (v = u(gt, v, lt), vt === null ? Z = gt : vt.sibling = gt, vt = gt);
        return ot && bl(b, lt), Z;
      }
      for (tt = a(tt); !gt.done; lt++, gt = S.next())
        gt = T(tt, b, lt, gt.value, O), gt !== null && (t && (Jt = gt.alternate, Jt !== null && tt.delete(
          Jt.key === null ? lt : Jt.key
        )), v = u(gt, v, lt), vt === null ? Z = gt : vt.sibling = gt, vt = gt);
      return t && tt.forEach(function(kv) {
        return e(b, kv);
      }), ot && bl(b, lt), Z;
    }
    function ct(b, v, S, O) {
      if (typeof S == "object" && S !== null && S.type === Yt && S.key === null && S.props.ref === void 0 && (S = S.props.children), typeof S == "object" && S !== null) {
        switch (S.$$typeof) {
          case qt:
            t: {
              for (var Z = S.key; v !== null; ) {
                if (v.key === Z) {
                  if (Z = S.type, Z === Yt) {
                    if (v.tag === 7) {
                      l(
                        b,
                        v.sibling
                      ), O = n(
                        v,
                        S.props.children
                      ), Bl(O, S), O.return = b, b = O;
                      break t;
                    }
                  } else if (v.elementType === Z || typeof Z == "object" && Z !== null && Z.$$typeof === st && ga(Z) === v.type) {
                    l(
                      b,
                      v.sibling
                    ), O = n(v, S.props), Bl(O, S), O.return = b, b = O;
                    break t;
                  }
                  l(b, v);
                  break;
                } else e(b, v);
                v = v.sibling;
              }
              S.type === Yt ? (O = oa(
                S.props.children,
                b.mode,
                O,
                S.key
              ), Bl(O, S), O.return = b, b = O) : (O = Ku(
                S.type,
                S.key,
                S.props,
                null,
                b.mode,
                O
              ), Bl(O, S), O.return = b, b = O);
            }
            return i(b);
          case xt:
            t: {
              for (Z = S.key; v !== null; ) {
                if (v.key === Z)
                  if (v.tag === 4 && v.stateNode.containerInfo === S.containerInfo && v.stateNode.implementation === S.implementation) {
                    l(
                      b,
                      v.sibling
                    ), O = n(v, S.children || []), O.return = b, b = O;
                    break t;
                  } else {
                    l(b, v);
                    break;
                  }
                else e(b, v);
                v = v.sibling;
              }
              O = Lc(S, b.mode, O), O.return = b, b = O;
            }
            return i(b);
          case st:
            return S = ga(S), ct(
              b,
              v,
              S,
              O
            );
        }
        if (et(S))
          return L(
            b,
            v,
            S,
            O
          );
        if (U(S)) {
          if (Z = U(S), typeof Z != "function") throw Error(o(150));
          return S = Z.call(S), $(
            b,
            v,
            S,
            O
          );
        }
        if (typeof S.then == "function")
          return ct(
            b,
            v,
            li(S),
            O
          );
        if (S.$$typeof === Rt)
          return ct(
            b,
            v,
            Iu(b, S),
            O
          );
        ai(b, S);
      }
      return typeof S == "string" && S !== "" || typeof S == "number" || typeof S == "bigint" ? (S = "" + S, v !== null && v.tag === 6 ? (l(b, v.sibling), O = n(v, S), O.return = b, b = O) : (l(b, v), O = Yc(S, b.mode, O), O.return = b, b = O), i(b)) : l(b, v);
    }
    return function(b, v, S, O) {
      try {
        Qn = 0;
        var Z = ct(
          b,
          v,
          S,
          O
        );
        return ka = null, Z;
      } catch (tt) {
        if (tt === Ka || tt === ti) throw tt;
        var vt = ve(29, tt, null, b.mode);
        return vt.lanes = O, vt.return = b, vt;
      }
    };
  }
  var ba = jr(!0), zr = jr(!1), ql = !1;
  function Fc(t) {
    t.updateQueue = {
      baseState: t.memoizedState,
      firstBaseUpdate: null,
      lastBaseUpdate: null,
      shared: { pending: null, lanes: 0, hiddenCallbacks: null },
      callbacks: null
    };
  }
  function Wc(t, e) {
    t = t.updateQueue, e.updateQueue === t && (e.updateQueue = {
      baseState: t.baseState,
      firstBaseUpdate: t.firstBaseUpdate,
      lastBaseUpdate: t.lastBaseUpdate,
      shared: t.shared,
      callbacks: null
    });
  }
  function Yl(t) {
    return { lane: t, tag: 0, payload: null, callback: null, next: null };
  }
  function Ll(t, e, l) {
    var a = t.updateQueue;
    if (a === null) return null;
    if (a = a.shared, (_t & 2) !== 0) {
      var n = a.pending;
      return n === null ? e.next = e : (e.next = n.next, n.next = e), a.pending = e, e = Zu(t), or(t, null, l), e;
    }
    return Vu(t, a, e, l), Zu(t);
  }
  function Vn(t, e, l) {
    if (e = e.updateQueue, e !== null && (e = e.shared, (l & 4194048) !== 0)) {
      var a = e.lanes;
      a &= t.pendingLanes, l |= a, e.lanes = l, ho(t, l);
    }
  }
  function Ic(t, e) {
    var l = t.updateQueue, a = t.alternate;
    if (a !== null && (a = a.updateQueue, l === a)) {
      var n = null, u = null;
      if (l = l.firstBaseUpdate, l !== null) {
        do {
          var i = {
            lane: l.lane,
            tag: l.tag,
            payload: l.payload,
            callback: null,
            next: null
          };
          u === null ? n = u = i : u = u.next = i, l = l.next;
        } while (l !== null);
        u === null ? n = u = e : u = u.next = e;
      } else n = u = e;
      l = {
        baseState: a.baseState,
        firstBaseUpdate: n,
        lastBaseUpdate: u,
        shared: a.shared,
        callbacks: a.callbacks
      }, t.updateQueue = l;
      return;
    }
    t = l.lastBaseUpdate, t === null ? l.firstBaseUpdate = e : t.next = e, l.lastBaseUpdate = e;
  }
  var Pc = !1;
  function Zn() {
    if (Pc) {
      var t = Za;
      if (t !== null) throw t;
    }
  }
  function Kn(t, e, l, a) {
    Pc = !1;
    var n = t.updateQueue;
    ql = !1;
    var u = n.firstBaseUpdate, i = n.lastBaseUpdate, f = n.shared.pending;
    if (f !== null) {
      n.shared.pending = null;
      var m = f, x = m.next;
      m.next = null, i === null ? u = x : i.next = x, i = m;
      var j = t.alternate;
      j !== null && (j = j.updateQueue, f = j.lastBaseUpdate, f !== i && (f === null ? j.firstBaseUpdate = x : f.next = x, j.lastBaseUpdate = m));
    }
    if (u !== null) {
      var C = n.baseState;
      i = 0, j = x = m = null, f = u;
      do {
        var g = f.lane & -536870913, T = g !== f.lane;
        if (T ? (yt & g) === g : (a & g) === g) {
          g !== 0 && g === ya && (Pc = !0), j !== null && (j = j.next = {
            lane: 0,
            tag: f.tag,
            payload: f.payload,
            callback: null,
            next: null
          });
          t: {
            var L = t, $ = f;
            g = e;
            var ct = l;
            switch ($.tag) {
              case 1:
                if (L = $.payload, typeof L == "function") {
                  C = L.call(ct, C, g);
                  break t;
                }
                C = L;
                break t;
              case 3:
                L.flags = L.flags & -65537 | 128;
              case 0:
                if (L = $.payload, g = typeof L == "function" ? L.call(ct, C, g) : L, g == null) break t;
                C = V({}, C, g);
                break t;
              case 2:
                ql = !0;
            }
          }
          g = f.callback, g !== null && (t.flags |= 64, T && (t.flags |= 8192), T = n.callbacks, T === null ? n.callbacks = [g] : T.push(g));
        } else
          T = {
            lane: g,
            tag: f.tag,
            payload: f.payload,
            callback: f.callback,
            next: null
          }, j === null ? (x = j = T, m = C) : j = j.next = T, i |= g;
        if (f = f.next, f === null) {
          if (f = n.shared.pending, f === null)
            break;
          T = f, f = T.next, T.next = null, n.lastBaseUpdate = T, n.shared.pending = null;
        }
      } while (!0);
      j === null && (m = C), n.baseState = m, n.firstBaseUpdate = x, n.lastBaseUpdate = j, u === null && (n.shared.lanes = 0), kl |= i, t.lanes = i, t.memoizedState = C;
    }
  }
  function Ar(t, e) {
    if (typeof t != "function")
      throw Error(o(191, t));
    t.call(e);
  }
  function Or(t, e) {
    var l = t.callbacks;
    if (l !== null)
      for (t.callbacks = null, t = 0; t < l.length; t++)
        Ar(l[t], e);
  }
  var Xl = we(null), ni = we(0);
  function Mr(t, e) {
    t = jl, Ot(ni, t), Ot(Xl, e), jl = t | e.baseLanes;
  }
  function ts() {
    Ot(ni, jl), Ot(Xl, Xl.current);
  }
  function es() {
    jl = ni.current, Qt(Xl), Qt(ni);
  }
  var ne = we(null), fe = null;
  function Gl(t) {
    var e = t.alternate;
    Ot(ue, ue.current & 1), Ot(ne, t), fe === null && (e === null || Xl.current !== null || e.memoizedState !== null) && (fe = t);
  }
  function ls(t) {
    Ot(ue, ue.current), Ot(ne, t), fe === null && (fe = t);
  }
  function Cr(t) {
    t.tag === 22 ? (Ot(ue, ue.current), Ot(ne, t), fe === null && (fe = t)) : Ql();
  }
  function Ql() {
    Ot(ue, ue.current), Ot(ne, ne.current);
  }
  function ze(t) {
    Qt(ne), fe === t && (fe = null), Qt(ue);
  }
  var ue = we(0);
  function kn(t, e) {
    Ot(ne, ne.current), Ot(ue, e);
  }
  function as(t) {
    Qt(ue), Qt(ne), fe === t && (fe = null);
  }
  function ui(t) {
    for (var e = t; e !== null; ) {
      if (e.tag === 13) {
        var l = e.memoizedState;
        if (l !== null && (l = l.dehydrated, l === null || jf(l) || zf(l)))
          return e;
      } else if (e.tag === 19 && e.memoizedProps.revealOrder !== "independent") {
        if ((e.flags & 128) !== 0) return e;
      } else if (e.child !== null) {
        e.child.return = e, e = e.child;
        continue;
      }
      if (e === t) break;
      for (; e.sibling === null; ) {
        if (e.return === null || e.return === t) return null;
        e = e.return;
      }
      e.sibling.return = e.return, e = e.sibling;
    }
    return null;
  }
  var _l = 0, it = null, zt = null, Kt = null, ii = !1, Ja = !1, xa = !1, ci = 0, Jn = 0, $a = null, hy = 0;
  function Xt() {
    throw Error(o(321));
  }
  function ns(t, e) {
    if (e === null) return !1;
    for (var l = 0; l < e.length && l < t.length; l++)
      if (!je(t[l], e[l])) return !1;
    return !0;
  }
  function us(t, e, l, a, n, u) {
    return _l = u, it = e, e.memoizedState = null, e.updateQueue = null, e.lanes = 0, G.H = t === null || t.memoizedState === null ? hd : yd, xa = !1, u = l(a, n), xa = !1, Ja && (u = Dr(
      e,
      l,
      a,
      n
    )), Rr(t), u;
  }
  function Rr(t) {
    G.H = hi;
    var e = zt !== null && zt.next !== null;
    if (_l = 0, Kt = zt = it = null, ii = !1, Jn = 0, $a = null, e) throw Error(o(300));
    t === null || kt || (t = t.dependencies, t !== null && Wu(t) && (kt = !0));
  }
  function Dr(t, e, l, a) {
    it = t;
    var n = 0;
    do {
      if (Ja && ($a = null), Jn = 0, Ja = !1, 25 <= n) throw Error(o(301));
      if (n += 1, Kt = zt = null, t.updateQueue != null) {
        var u = t.updateQueue;
        u.lastEffect = null, u.events = null, u.stores = null, u.memoCache != null && (u.memoCache.index = 0);
      }
      G.H = _y, u = e(l, a);
    } while (Ja);
    return u;
  }
  function yy() {
    var t = G.H, e = t.useState()[0];
    return e = typeof e.then == "function" ? $n(e) : e, t = t.useState()[0], (zt !== null ? zt.memoizedState : null) !== t && (it.flags |= 1024), e;
  }
  function is() {
    var t = ci !== 0;
    return ci = 0, t;
  }
  function cs(t, e, l) {
    e.updateQueue = t.updateQueue, e.flags &= -2053, t.lanes &= ~l;
  }
  function ss(t) {
    if (ii) {
      for (t = t.memoizedState; t !== null; ) {
        var e = t.queue;
        e !== null && (e.pending = null), t = t.next;
      }
      ii = !1;
    }
    _l = 0, Kt = zt = it = null, Ja = !1, Jn = ci = 0, $a = null;
  }
  function re() {
    var t = {
      memoizedState: null,
      baseState: null,
      baseQueue: null,
      queue: null,
      next: null
    };
    return Kt === null ? it.memoizedState = Kt = t : Kt = Kt.next = t, Kt;
  }
  function Vt() {
    if (zt === null) {
      var t = it.alternate;
      t = t !== null ? t.memoizedState : null;
    } else t = zt.next;
    var e = Kt === null ? it.memoizedState : Kt.next;
    if (e !== null)
      Kt = e, zt = t;
    else {
      if (t === null)
        throw it.alternate === null ? Error(o(467)) : Error(o(310));
      zt = t, t = {
        memoizedState: zt.memoizedState,
        baseState: zt.baseState,
        baseQueue: zt.baseQueue,
        queue: zt.queue,
        next: null
      }, Kt === null ? it.memoizedState = Kt = t : Kt = Kt.next = t;
    }
    return Kt;
  }
  function si() {
    return { lastEffect: null, events: null, stores: null, memoCache: null };
  }
  function $n(t) {
    var e = Jn;
    return Jn += 1, $a === null && ($a = []), t = Nr($a, t, e), e = it, (Kt === null ? e.memoizedState : Kt.next) === null && (e = e.alternate, G.H = e === null || e.memoizedState === null ? hd : yd), t;
  }
  function fi(t) {
    if (t !== null && typeof t == "object") {
      if (typeof t.then == "function") return $n(t);
      if (t.$$typeof === E) return;
      if (t.$$typeof === Rt) return ae(t);
    }
    throw Error(o(438, String(t)));
  }
  function fs(t) {
    var e = null, l = it.updateQueue;
    if (l !== null && (e = l.memoCache), e == null) {
      var a = it.alternate;
      a !== null && (a = a.updateQueue, a !== null && (a = a.memoCache, a != null && (e = {
        data: a.data.map(function(n) {
          return n.slice();
        }),
        index: 0
      })));
    }
    if (e == null && (e = { data: [], index: 0 }), l === null && (l = si(), it.updateQueue = l), l.memoCache = e, l = e.data[e.index], l === void 0)
      for (l = e.data[e.index] = Array(t), a = 0; a < t; a++)
        l[a] = A;
    return e.index++, l;
  }
  function Nl(t, e) {
    return typeof e == "function" ? e(t) : e;
  }
  function oi(t) {
    var e = Vt();
    return os(e, zt, t);
  }
  function os(t, e, l) {
    var a = t.queue;
    if (a === null) throw Error(o(311));
    a.lastRenderedReducer = l;
    var n = t.baseQueue, u = a.pending;
    if (u !== null) {
      if (n !== null) {
        var i = n.next;
        n.next = u.next, u.next = i;
      }
      e.baseQueue = n = u, a.pending = null;
    }
    if (u = t.baseState, n === null) t.memoizedState = u;
    else {
      e = n.next;
      var f = i = null, m = null, x = e, j = !1;
      do {
        var C = x.lane & -536870913;
        if (C !== x.lane ? (yt & C) === C : (_l & C) === C) {
          var g = x.revertLane;
          if (g === 0)
            m !== null && (m = m.next = {
              lane: 0,
              revertLane: 0,
              gesture: null,
              action: x.action,
              hasEagerState: x.hasEagerState,
              eagerState: x.eagerState,
              next: null
            }), C === ya && (j = !0);
          else if ((_l & g) === g) {
            x = x.next, g === ya && (j = !0);
            continue;
          } else
            C = {
              lane: 0,
              revertLane: x.revertLane,
              gesture: null,
              action: x.action,
              hasEagerState: x.hasEagerState,
              eagerState: x.eagerState,
              next: null
            }, m === null ? (f = m = C, i = u) : m = m.next = C, it.lanes |= g, kl |= g;
          C = x.action, xa && l(u, C), u = x.hasEagerState ? x.eagerState : l(u, C);
        } else
          g = {
            lane: C,
            revertLane: x.revertLane,
            gesture: x.gesture,
            action: x.action,
            hasEagerState: x.hasEagerState,
            eagerState: x.eagerState,
            next: null
          }, m === null ? (f = m = g, i = u) : m = m.next = g, it.lanes |= C, kl |= C;
        x = x.next;
      } while (x !== null && x !== e);
      if (m === null ? i = u : m.next = f, !je(u, t.memoizedState) && (kt = !0, j && (l = Za, l !== null)))
        throw l;
      t.memoizedState = u, t.baseState = i, t.baseQueue = m, a.lastRenderedState = u;
    }
    return n === null && (a.lanes = 0), [t.memoizedState, a.dispatch];
  }
  function rs(t) {
    var e = Vt(), l = e.queue;
    if (l === null) throw Error(o(311));
    l.lastRenderedReducer = t;
    var a = l.dispatch, n = l.pending, u = e.memoizedState;
    if (n !== null) {
      l.pending = null;
      var i = n = n.next;
      do
        u = t(u, i.action), i = i.next;
      while (i !== n);
      je(u, e.memoizedState) || (kt = !0), e.memoizedState = u, e.baseQueue === null && (e.baseState = u), l.lastRenderedState = u;
    }
    return [u, a];
  }
  function Ur(t, e, l) {
    var a = it, n = Vt(), u = ot;
    if (u) {
      if (l === void 0) throw Error(o(407));
      l = l();
    } else l = e();
    var i = !je(
      (zt || n).memoizedState,
      l
    );
    if (i && (n.memoizedState = l, kt = !0), n = n.queue, hs(Br.bind(null, a, n, t), [
      t
    ]), t = n.getSnapshot !== e || i || Kt !== null && (Kt.memoizedState.tag & 1) !== 0, Fa(
      t ? 9 : 8,
      { destroy: void 0 },
      Hr.bind(null, a, n, l, e),
      null
    ), t) {
      if (a.flags |= 2048, At === null) throw Error(o(349));
      u || (_l & 127) !== 0 || wr(a, e, l);
    }
    return l;
  }
  function wr(t, e, l) {
    t.flags |= 16384, t = { getSnapshot: e, value: l }, e = it.updateQueue, e === null ? (e = si(), it.updateQueue = e, e.stores = [t]) : (l = e.stores, l === null ? e.stores = [t] : l.push(t));
  }
  function Hr(t, e, l, a) {
    e.value = l, e.getSnapshot = a, qr(e) && Yr(t);
  }
  function Br(t, e, l) {
    return l(function() {
      qr(e) && Yr(t);
    });
  }
  function qr(t) {
    var e = t.getSnapshot;
    t = t.value;
    try {
      var l = e();
      return !je(t, l);
    } catch {
      return !0;
    }
  }
  function Yr(t) {
    var e = fa(t, 2);
    e !== null && xe(e, t, 2);
  }
  function ds(t) {
    var e = re();
    if (typeof t == "function") {
      var l = t;
      if (t = l(), xa) {
        Ml(!0);
        try {
          l();
        } finally {
          Ml(!1);
        }
      }
    }
    return e.memoizedState = e.baseState = t, e.queue = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: Nl,
      lastRenderedState: t
    }, e;
  }
  function Lr(t, e, l, a) {
    return t.baseState = l, os(
      t,
      zt,
      typeof a == "function" ? a : Nl
    );
  }
  function vy(t, e, l, a, n) {
    if (mi(t)) throw Error(o(485));
    if (t = e.action, t !== null) {
      var u = {
        payload: n,
        action: t,
        next: null,
        isTransition: !0,
        status: "pending",
        value: null,
        reason: null,
        listeners: [],
        then: function(i) {
          u.listeners.push(i);
        }
      };
      G.T !== null ? l(!0) : u.isTransition = !1, a(u), l = e.pending, l === null ? (u.next = e.pending = u, Xr(e, u)) : (u.next = l.next, e.pending = l.next = u);
    }
  }
  function Xr(t, e) {
    var l = e.action, a = e.payload, n = t.state;
    if (e.isTransition) {
      var u = G.T, i = {};
      i.types = u !== null ? u.types : null, G.T = i;
      try {
        var f = l(n, a), m = G.S;
        m !== null && m(i, f), Gr(t, e, f);
      } catch (x) {
        ms(t, e, x);
      } finally {
        u !== null && i.types !== null && (u.types = i.types), G.T = u;
      }
    } else
      try {
        u = l(n, a), Gr(t, e, u);
      } catch (x) {
        ms(t, e, x);
      }
  }
  function Gr(t, e, l) {
    l !== null && typeof l == "object" && typeof l.then == "function" ? l.then(
      function(a) {
        Qr(t, e, a);
      },
      function(a) {
        return ms(t, e, a);
      }
    ) : Qr(t, e, l);
  }
  function Qr(t, e, l) {
    e.status = "fulfilled", e.value = l, Vr(e), t.state = l, e = t.pending, e !== null && (l = e.next, l === e ? t.pending = null : (l = l.next, e.next = l, Xr(t, l)));
  }
  function ms(t, e, l) {
    var a = t.pending;
    if (t.pending = null, a !== null) {
      a = a.next;
      do
        e.status = "rejected", e.reason = l, Vr(e), e = e.next;
      while (e !== a);
    }
    t.action = null;
  }
  function Vr(t) {
    t = t.listeners;
    for (var e = 0; e < t.length; e++) (0, t[e])();
  }
  function Zr(t, e) {
    return e;
  }
  function Kr(t, e) {
    if (ot) {
      var l = At.formState;
      if (l !== null) {
        t: {
          var a = it;
          if (ot) {
            if (Mt) {
              e: {
                for (var n = Mt, u = Xe; n.nodeType !== 8; ) {
                  if (!u) {
                    n = null;
                    break e;
                  }
                  if (n = Qe(
                    n.nextSibling
                  ), n === null) {
                    n = null;
                    break e;
                  }
                }
                u = n.data, n = u === "F!" || u === "F" ? n : null;
              }
              if (n) {
                Mt = Qe(
                  n.nextSibling
                ), a = n.data === "F!";
                break t;
              }
            }
            wl(a);
          }
          a = !1;
        }
        a && (e = l[0]);
      }
    }
    return l = re(), l.memoizedState = l.baseState = e, a = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: Zr,
      lastRenderedState: e
    }, l.queue = a, l = rd.bind(
      null,
      it,
      a
    ), a.dispatch = l, a = ds(!1), u = bs.bind(
      null,
      it,
      !1,
      a.queue
    ), a = re(), n = {
      state: e,
      dispatch: null,
      action: t,
      pending: null
    }, a.queue = n, l = vy.bind(
      null,
      it,
      n,
      u,
      l
    ), n.dispatch = l, a.memoizedState = t, [e, l, !1];
  }
  function kr(t) {
    var e = Vt();
    return Jr(e, zt, t);
  }
  function Jr(t, e, l) {
    if (e = os(
      t,
      e,
      Zr
    )[0], t = oi(Nl)[0], typeof e == "object" && e !== null && typeof e.then == "function")
      try {
        var a = $n(e);
      } catch (i) {
        throw i === Ka ? ti : i;
      }
    else a = e;
    e = Vt();
    var n = e.queue, u = n.dispatch;
    return l !== e.memoizedState && (it.flags |= 2048, Fa(
      9,
      { destroy: void 0 },
      gy.bind(null, n, l),
      null
    )), [a, u, t];
  }
  function gy(t, e) {
    t.action = e;
  }
  function $r(t) {
    var e = Vt(), l = zt;
    if (l !== null)
      return Jr(e, l, t);
    Vt(), e = e.memoizedState, l = Vt();
    var a = l.queue.dispatch;
    return l.memoizedState = t, [e, a, !1];
  }
  function Fa(t, e, l, a) {
    return t = { tag: t, create: l, deps: a, inst: e, next: null }, e = it.updateQueue, e === null && (e = si(), it.updateQueue = e), l = e.lastEffect, l === null ? e.lastEffect = t.next = t : (a = l.next, l.next = t, t.next = a, e.lastEffect = t), t;
  }
  function Fr() {
    return Vt().memoizedState;
  }
  function ri(t, e, l, a) {
    var n = re();
    it.flags |= t, n.memoizedState = Fa(
      1 | e,
      { destroy: void 0 },
      l,
      a === void 0 ? null : a
    );
  }
  function di(t, e, l, a) {
    var n = Vt();
    a = a === void 0 ? null : a;
    var u = n.memoizedState.inst;
    zt !== null && a !== null && ns(a, zt.memoizedState.deps) ? n.memoizedState = Fa(e, u, l, a) : (it.flags |= t, n.memoizedState = Fa(
      1 | e,
      u,
      l,
      a
    ));
  }
  function Wr(t, e) {
    ri(8390656, 8, t, e);
  }
  function hs(t, e) {
    di(2048, 8, t, e);
  }
  function py(t) {
    it.flags |= 4;
    var e = it.updateQueue;
    if (e === null)
      e = si(), it.updateQueue = e, e.events = [t];
    else {
      var l = e.events;
      l === null ? e.events = [t] : l.push(t);
    }
  }
  function Ir(t) {
    var e = Vt().memoizedState;
    return py({ ref: e, nextImpl: t }), function() {
      if ((_t & 2) !== 0) throw Error(o(440));
      return e.impl.apply(void 0, arguments);
    };
  }
  function Pr(t, e) {
    return di(4, 2, t, e);
  }
  function td(t, e) {
    return di(4, 4, t, e);
  }
  function ed(t, e) {
    if (typeof e == "function") {
      t = t();
      var l = e(t);
      return function() {
        typeof l == "function" ? l() : e(null);
      };
    }
    if (e != null)
      return t = t(), e.current = t, function() {
        e.current = null;
      };
  }
  function ld(t, e, l) {
    l = l != null ? l.concat([t]) : null, di(4, 4, ed.bind(null, e, t), l);
  }
  function ys() {
  }
  function ad(t, e) {
    var l = Vt();
    e = e === void 0 ? null : e;
    var a = l.memoizedState;
    return e !== null && ns(e, a[1]) ? a[0] : (l.memoizedState = [t, e], t);
  }
  function nd(t, e) {
    var l = Vt();
    e = e === void 0 ? null : e;
    var a = l.memoizedState;
    if (e !== null && ns(e, a[1]))
      return a[0];
    if (a = t(), xa) {
      Ml(!0);
      try {
        t();
      } finally {
        Ml(!1);
      }
    }
    return l.memoizedState = [a, e], a;
  }
  function vs(t, e, l) {
    return l === void 0 || (_l & 1073741824) !== 0 && (yt & 261930) === 0 ? t.memoizedState = e : (t.memoizedState = l, t = hm(), it.lanes |= t, kl |= t, l);
  }
  function ud(t, e, l, a) {
    return je(l, e) ? l : Xl.current !== null ? (t = vs(t, l, a), je(t, e) || (kt = !0), t) : (_l & 106) === 0 || (_l & 1073741824) !== 0 && (yt & 261930) === 0 ? (kt = !0, t.memoizedState = l) : (t = hm(), it.lanes |= t, kl |= t, e);
  }
  function id(t, e, l, a, n) {
    var u = W.p;
    W.p = u !== 0 && 8 > u ? u : 8;
    var i = G.T, f = {};
    f.types = i !== null ? i.types : null, G.T = f, bs(t, !1, e, l);
    try {
      var m = n(), x = G.S;
      if (x !== null && x(f, m), m !== null && typeof m == "object" && typeof m.then == "function") {
        var j = my(
          m,
          a
        );
        Fn(
          t,
          e,
          j,
          Ce(t)
        );
      } else
        Fn(
          t,
          e,
          a,
          Ce(t)
        );
    } catch (C) {
      Fn(
        t,
        e,
        { then: function() {
        }, status: "rejected", reason: C },
        Ce()
      );
    } finally {
      W.p = u, i !== null && f.types !== null && (i.types = f.types), G.T = i;
    }
  }
  function by() {
  }
  function gs(t, e, l, a) {
    if (t.tag !== 5) throw Error(o(476));
    var n = cd(t).queue;
    id(
      t,
      n,
      e,
      Dt,
      l === null ? by : function() {
        return sd(t), l(a);
      }
    );
  }
  function cd(t) {
    var e = t.memoizedState;
    if (e !== null) return e;
    e = {
      memoizedState: Dt,
      baseState: Dt,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: Nl,
        lastRenderedState: Dt
      },
      next: null
    };
    var l = {};
    return e.next = {
      memoizedState: l,
      baseState: l,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: Nl,
        lastRenderedState: l
      },
      next: null
    }, t.memoizedState = e, t = t.alternate, t !== null && (t.memoizedState = e), e;
  }
  function sd(t) {
    var e = cd(t);
    e.next === null && (e = t.alternate.memoizedState), Fn(
      t,
      e.next.queue,
      {},
      Ce()
    );
  }
  function ps() {
    return ae(vn);
  }
  function fd() {
    return Vt().memoizedState;
  }
  function od() {
    return Vt().memoizedState;
  }
  function xy(t) {
    for (var e = t.return; e !== null; ) {
      switch (e.tag) {
        case 24:
        case 3:
          var l = Ce();
          t = Yl(l);
          var a = Ll(e, t, l);
          a !== null && (xe(a, e, l), Vn(a, e, l)), e = { cache: Kc() }, t.payload = e;
          return;
      }
      e = e.return;
    }
  }
  function Sy(t, e, l) {
    var a = Ce();
    l = {
      lane: a,
      revertLane: 0,
      gesture: null,
      action: l,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, mi(t) ? dd(e, l) : (l = Bc(t, e, l, a), l !== null && (xe(l, t, a), md(l, e, a)));
  }
  function rd(t, e, l) {
    var a = Ce();
    Fn(t, e, l, a);
  }
  function Fn(t, e, l, a) {
    var n = {
      lane: a,
      revertLane: 0,
      gesture: null,
      action: l,
      hasEagerState: !1,
      eagerState: null,
      next: null
    };
    if (mi(t)) dd(e, n);
    else {
      var u = t.alternate;
      if (t.lanes === 0 && (u === null || u.lanes === 0) && (u = e.lastRenderedReducer, u !== null))
        try {
          var i = e.lastRenderedState, f = u(i, l);
          if (n.hasEagerState = !0, n.eagerState = f, je(f, i))
            return Vu(t, e, n, 0), At === null && Qu(), !1;
        } catch {
        }
      if (l = Bc(t, e, n, a), l !== null)
        return xe(l, t, a), md(l, e, a), !0;
    }
    return !1;
  }
  function bs(t, e, l, a) {
    if (a = {
      lane: 2,
      revertLane: of(),
      gesture: null,
      action: a,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, mi(t)) {
      if (e) throw Error(o(479));
    } else
      e = Bc(
        t,
        l,
        a,
        2
      ), e !== null && xe(e, t, 2);
  }
  function mi(t) {
    var e = t.alternate;
    return t === it || e !== null && e === it;
  }
  function dd(t, e) {
    Ja = ii = !0;
    var l = t.pending;
    l === null ? e.next = e : (e.next = l.next, l.next = e), t.pending = e;
  }
  function md(t, e, l) {
    if ((l & 4194048) !== 0) {
      var a = e.lanes;
      a &= t.pendingLanes, l |= a, e.lanes = l, ho(t, l);
    }
  }
  var hi = {
    readContext: ae,
    use: fi,
    useCallback: Xt,
    useContext: Xt,
    useEffect: Xt,
    useImperativeHandle: Xt,
    useLayoutEffect: Xt,
    useInsertionEffect: Xt,
    useMemo: Xt,
    useReducer: Xt,
    useRef: Xt,
    useState: Xt,
    useDebugValue: Xt,
    useDeferredValue: Xt,
    useTransition: Xt,
    useSyncExternalStore: Xt,
    useId: Xt,
    useHostTransitionStatus: Xt,
    useFormState: Xt,
    useActionState: Xt,
    useOptimistic: Xt,
    useMemoCache: Xt,
    useCacheRefresh: Xt,
    useEffectEvent: Xt
  }, hd = {
    readContext: ae,
    use: fi,
    useCallback: function(t, e) {
      return re().memoizedState = [
        t,
        e === void 0 ? null : e
      ], t;
    },
    useContext: ae,
    useEffect: Wr,
    useImperativeHandle: function(t, e, l) {
      l = l != null ? l.concat([t]) : null, ri(
        4194308,
        4,
        ed.bind(null, e, t),
        l
      );
    },
    useLayoutEffect: function(t, e) {
      return ri(4194308, 4, t, e);
    },
    useInsertionEffect: function(t, e) {
      ri(4, 2, t, e);
    },
    useMemo: function(t, e) {
      var l = re();
      e = e === void 0 ? null : e;
      var a = t();
      if (xa) {
        Ml(!0);
        try {
          t();
        } finally {
          Ml(!1);
        }
      }
      return l.memoizedState = [a, e], a;
    },
    useReducer: function(t, e, l) {
      var a = re();
      if (l !== void 0) {
        var n = l(e);
        if (xa) {
          Ml(!0);
          try {
            l(e);
          } finally {
            Ml(!1);
          }
        }
      } else n = e;
      return a.memoizedState = a.baseState = n, t = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: t,
        lastRenderedState: n
      }, a.queue = t, t = t.dispatch = Sy.bind(
        null,
        it,
        t
      ), [a.memoizedState, t];
    },
    useRef: function(t) {
      var e = re();
      return t = { current: t }, e.memoizedState = t;
    },
    useState: function(t) {
      t = ds(t);
      var e = t.queue, l = rd.bind(null, it, e);
      return e.dispatch = l, [t.memoizedState, l];
    },
    useDebugValue: ys,
    useDeferredValue: function(t, e) {
      var l = re();
      return vs(l, t, e);
    },
    useTransition: function() {
      var t = ds(!1);
      return t = id.bind(
        null,
        it,
        t.queue,
        !0,
        !1
      ), re().memoizedState = t, [!1, t];
    },
    useSyncExternalStore: function(t, e, l) {
      var a = it, n = re();
      if (ot) {
        if (l === void 0)
          throw Error(o(407));
        l = l();
      } else {
        if (l = e(), At === null)
          throw Error(o(349));
        (yt & 127) !== 0 || wr(a, e, l);
      }
      n.memoizedState = l;
      var u = { value: l, getSnapshot: e };
      return n.queue = u, Wr(Br.bind(null, a, u, t), [
        t
      ]), a.flags |= 2048, Fa(
        9,
        { destroy: void 0 },
        Hr.bind(
          null,
          a,
          u,
          l,
          e
        ),
        null
      ), l;
    },
    useId: function() {
      var t = re(), e = At.identifierPrefix;
      if (ot) {
        var l = ll, a = el;
        l = (a & ~(1 << 32 - Te(a) - 1)).toString(32) + l, e = "_" + e + "R_" + l, l = ci++, 0 < l && (e += "H" + l.toString(32)), e += "_";
      } else
        l = hy++, e = "_" + e + "r_" + l.toString(32) + "_";
      return t.memoizedState = e;
    },
    useHostTransitionStatus: ps,
    useFormState: Kr,
    useActionState: Kr,
    useOptimistic: function(t) {
      var e = re();
      e.memoizedState = e.baseState = t;
      var l = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: null,
        lastRenderedState: null
      };
      return e.queue = l, e = bs.bind(
        null,
        it,
        !0,
        l
      ), l.dispatch = e, [t, e];
    },
    useMemoCache: fs,
    useCacheRefresh: function() {
      return re().memoizedState = xy.bind(
        null,
        it
      );
    },
    useEffectEvent: function(t) {
      var e = re(), l = { impl: t };
      return e.memoizedState = l, function() {
        if ((_t & 2) !== 0)
          throw Error(o(440));
        return l.impl.apply(void 0, arguments);
      };
    }
  }, yd = {
    readContext: ae,
    use: fi,
    useCallback: ad,
    useContext: ae,
    useEffect: hs,
    useImperativeHandle: ld,
    useInsertionEffect: Pr,
    useLayoutEffect: td,
    useMemo: nd,
    useReducer: oi,
    useRef: Fr,
    useState: function() {
      return oi(Nl);
    },
    useDebugValue: ys,
    useDeferredValue: function(t, e) {
      var l = Vt();
      return ud(
        l,
        zt.memoizedState,
        t,
        e
      );
    },
    useTransition: function() {
      var t = oi(Nl)[0], e = Vt().memoizedState;
      return [
        typeof t == "boolean" ? t : $n(t),
        e
      ];
    },
    useSyncExternalStore: Ur,
    useId: fd,
    useHostTransitionStatus: ps,
    useFormState: kr,
    useActionState: kr,
    useOptimistic: function(t, e) {
      var l = Vt();
      return Lr(l, zt, t, e);
    },
    useMemoCache: fs,
    useCacheRefresh: od,
    useEffectEvent: Ir
  }, _y = {
    readContext: ae,
    use: fi,
    useCallback: ad,
    useContext: ae,
    useEffect: hs,
    useImperativeHandle: ld,
    useInsertionEffect: Pr,
    useLayoutEffect: td,
    useMemo: nd,
    useReducer: rs,
    useRef: Fr,
    useState: function() {
      return rs(Nl);
    },
    useDebugValue: ys,
    useDeferredValue: function(t, e) {
      var l = Vt();
      return zt === null ? vs(l, t, e) : ud(
        l,
        zt.memoizedState,
        t,
        e
      );
    },
    useTransition: function() {
      var t = rs(Nl)[0], e = Vt().memoizedState;
      return [
        typeof t == "boolean" ? t : $n(t),
        e
      ];
    },
    useSyncExternalStore: Ur,
    useId: fd,
    useHostTransitionStatus: ps,
    useFormState: $r,
    useActionState: $r,
    useOptimistic: function(t, e) {
      var l = Vt();
      return zt !== null ? Lr(l, zt, t, e) : (l.baseState = t, [t, l.queue.dispatch]);
    },
    useMemoCache: fs,
    useCacheRefresh: od,
    useEffectEvent: Ir
  };
  function xs(t, e, l, a) {
    e = t.memoizedState, l = l(a, e), l = l == null ? e : V({}, e, l), t.memoizedState = l, t.lanes === 0 && (t.updateQueue.baseState = l);
  }
  var Ss = {
    enqueueSetState: function(t, e, l) {
      t = t._reactInternals;
      var a = Ce(), n = Yl(a);
      n.payload = e, l != null && (n.callback = l), e = Ll(t, n, a), e !== null && (xe(e, t, a), Vn(e, t, a));
    },
    enqueueReplaceState: function(t, e, l) {
      t = t._reactInternals;
      var a = Ce(), n = Yl(a);
      n.tag = 1, n.payload = e, l != null && (n.callback = l), e = Ll(t, n, a), e !== null && (xe(e, t, a), Vn(e, t, a));
    },
    enqueueForceUpdate: function(t, e) {
      t = t._reactInternals;
      var l = Ce(), a = Yl(l);
      a.tag = 2, e != null && (a.callback = e), e = Ll(t, a, l), e !== null && (xe(e, t, l), Vn(e, t, l));
    }
  };
  function vd(t, e, l, a, n, u, i) {
    return t = t.stateNode, typeof t.shouldComponentUpdate == "function" ? t.shouldComponentUpdate(a, u, i) : e.prototype && e.prototype.isPureReactComponent ? !Hn(l, a) || !Hn(n, u) : !0;
  }
  function gd(t, e, l, a) {
    t = e.state, typeof e.componentWillReceiveProps == "function" && e.componentWillReceiveProps(l, a), typeof e.UNSAFE_componentWillReceiveProps == "function" && e.UNSAFE_componentWillReceiveProps(l, a), e.state !== t && Ss.enqueueReplaceState(e, e.state, null);
  }
  function Sa(t, e) {
    var l = e;
    if ("ref" in e) {
      l = {};
      for (var a in e)
        a !== "ref" && (l[a] = e[a]);
    }
    if (t = t.defaultProps) {
      l === e && (l = V({}, l));
      for (var n in t)
        l[n] === void 0 && (l[n] = t[n]);
    }
    return l;
  }
  function pd(t) {
    Gu(t);
  }
  function bd(t) {
    console.error(t);
  }
  function xd(t) {
    Gu(t);
  }
  function yi(t, e) {
    try {
      var l = t.onUncaughtError;
      l(e.value, { componentStack: e.stack });
    } catch (a) {
      setTimeout(function() {
        throw a;
      });
    }
  }
  function Sd(t, e, l) {
    try {
      var a = t.onCaughtError;
      a(l.value, {
        componentStack: l.stack,
        errorBoundary: e.tag === 1 ? e.stateNode : null
      });
    } catch (n) {
      setTimeout(function() {
        throw n;
      });
    }
  }
  function _s(t, e, l) {
    return l = Yl(l), l.tag = 3, l.payload = { element: null }, l.callback = function() {
      yi(t, e);
    }, l;
  }
  function _d(t) {
    return t = Yl(t), t.tag = 3, t;
  }
  function Nd(t, e, l, a) {
    var n = l.type.getDerivedStateFromError;
    if (typeof n == "function") {
      var u = a.value;
      t.payload = function() {
        return n(u);
      }, t.callback = function() {
        Sd(e, l, a);
      };
    }
    var i = l.stateNode;
    i !== null && typeof i.componentDidCatch == "function" && (t.callback = function() {
      Sd(e, l, a), typeof n != "function" && (Jl === null ? Jl = /* @__PURE__ */ new Set([this]) : Jl.add(this));
      var f = a.stack;
      this.componentDidCatch(a.value, {
        componentStack: f !== null ? f : ""
      });
    });
  }
  function Ny(t, e, l, a, n) {
    if (l.flags |= 32768, a !== null && typeof a == "object" && typeof a.then == "function") {
      if (e = l.alternate, e !== null && ma(
        e,
        l,
        n,
        !0
      ), l = ne.current, l !== null) {
        switch (l.tag) {
          case 31:
          case 13:
          case 19:
            return fe === null ? Hi() : l.alternate === null && Gt === 0 && (Gt = 3), l.flags &= -257, l.flags |= 65536, l.lanes = n, a === ei ? l.flags |= 16384 : (e = l.updateQueue, e === null ? l.updateQueue = /* @__PURE__ */ new Set([a]) : e.add(a), cf(t, a, n)), !1;
          case 22:
            return l.flags |= 65536, a === ei ? l.flags |= 16384 : (e = l.updateQueue, e === null ? (e = {
              transitions: null,
              markerInstances: null,
              retryQueue: /* @__PURE__ */ new Set([a])
            }, l.updateQueue = e) : (l = e.retryQueue, l === null ? e.retryQueue = /* @__PURE__ */ new Set([a]) : l.add(a)), cf(t, a, n)), !1;
        }
        throw Error(o(435, l.tag));
      }
      return cf(t, a, n), Hi(), !1;
    }
    if (ot)
      return e = ne.current, e !== null ? ((e.flags & 65536) === 0 && (e.flags |= 256), e.flags |= 65536, e.lanes = n, a !== Gc && (t = Error(o(422), { cause: a }), Yn(qe(t, l)))) : (a !== Gc && (e = Error(o(423), {
        cause: a
      }), Yn(
        qe(e, l)
      )), t = t.current.alternate, t.flags |= 65536, n &= -n, t.lanes |= n, a = qe(a, l), n = _s(
        t.stateNode,
        a,
        n
      ), Ic(t, n), Gt !== 4 && (Gt = 2)), !1;
    var u = Error(o(520), { cause: a });
    if (u = qe(u, l), nu === null ? nu = [u] : nu.push(u), Gt !== 4 && (Gt = 2), e === null) return !0;
    a = qe(a, l), l = e;
    do {
      switch (l.tag) {
        case 3:
          return l.flags |= 65536, t = n & -n, l.lanes |= t, t = _s(l.stateNode, a, t), Ic(l, t), !1;
        case 1:
          if (e = l.type, u = l.stateNode, (l.flags & 128) === 0 && (typeof e.getDerivedStateFromError == "function" || u !== null && typeof u.componentDidCatch == "function" && (Jl === null || !Jl.has(u))))
            return l.flags |= 65536, n &= -n, l.lanes |= n, n = _d(n), Nd(
              n,
              t,
              l,
              a
            ), Ic(l, n), !1;
          break;
        case 22:
          if (l.memoizedState !== null)
            return l.flags |= 65536, !1;
      }
      l = l.return;
    } while (l !== null);
    return !1;
  }
  var Ns = Error(o(461)), kt = !1;
  function Ft(t, e, l, a) {
    e.child = t === null ? zr(e, null, l, a) : ba(
      e,
      t.child,
      l,
      a
    );
  }
  function Td(t, e, l, a, n) {
    l = l.render;
    var u = e.ref;
    if ("ref" in a) {
      var i = {};
      for (var f in a)
        f !== "ref" && (i[f] = a[f]);
    } else i = a;
    return ha(e), a = us(
      t,
      e,
      l,
      i,
      u,
      n
    ), f = is(), t !== null && !kt ? (cs(t, e, n), Tl(t, e, n)) : (ot && f && Ju(e), e.flags |= 1, Ft(t, e, a, n), e.child);
  }
  function Ed(t, e, l, a, n) {
    if (t === null) {
      var u = l.type;
      return typeof u == "function" && !qc(u) && u.defaultProps === void 0 && l.compare === null ? (e.tag = 15, e.type = u, jd(
        t,
        e,
        u,
        a,
        n
      )) : (t = Ku(
        l.type,
        null,
        a,
        e,
        e.mode,
        n
      ), t.ref = e.ref, t.return = e, e.child = t);
    }
    if (u = t.child, !Cs(t, n)) {
      var i = u.memoizedProps;
      if (l = l.compare, l = l !== null ? l : Hn, l(i, a) && t.ref === e.ref)
        return Tl(t, e, n);
    }
    return e.flags |= 1, t = pl(u, a), t.ref = e.ref, t.return = e, e.child = t;
  }
  function jd(t, e, l, a, n) {
    if (t !== null) {
      var u = t.memoizedProps;
      if (Hn(u, a) && t.ref === e.ref)
        if (kt = !1, e.pendingProps = a = u, Cs(t, n))
          (t.flags & 131072) !== 0 && (kt = !0);
        else
          return e.lanes = t.lanes, Tl(t, e, n);
    }
    return Ts(
      t,
      e,
      l,
      a,
      n
    );
  }
  function zd(t, e, l, a) {
    var n = a.children, u = t !== null ? t.memoizedState : null;
    if (t === null && e.stateNode === null && (e.stateNode = {
      _visibility: 1,
      _pendingMarkers: null,
      _retryCache: null,
      _transitions: null
    }), a.mode === "hidden") {
      if ((e.flags & 128) !== 0) {
        if (u = u !== null ? u.baseLanes | l : l, t !== null) {
          for (a = e.child = t.child, n = 0; a !== null; )
            n = n | a.lanes | a.childLanes, a = a.sibling;
          a = n & ~u;
        } else a = 0, e.child = null;
        return Ad(
          t,
          e,
          u,
          l,
          a
        );
      }
      if ((l & 536870912) !== 0)
        e.memoizedState = { baseLanes: 0, cachePool: null }, t !== null && Pu(
          e,
          u !== null ? u.cachePool : null
        ), u !== null ? Mr(e, u) : ts(), Cr(e);
      else
        return a = e.lanes = 536870912, Ad(
          t,
          e,
          u !== null ? u.baseLanes | l : l,
          l,
          a
        );
    } else
      u !== null ? (Pu(e, u.cachePool), Mr(e, u), Ql(), e.memoizedState = null) : (t !== null && Pu(e, null), ts(), Ql());
    return Ft(t, e, n, l), e.child;
  }
  function Wn(t, e) {
    return t !== null && t.tag === 22 || e.stateNode !== null || (e.stateNode = {
      _visibility: 1,
      _pendingMarkers: null,
      _retryCache: null,
      _transitions: null
    }), e.sibling;
  }
  function Ad(t, e, l, a, n) {
    var u = Jc();
    return u = u === null ? null : { parent: Zt._currentValue, pool: u }, e.memoizedState = {
      baseLanes: l,
      cachePool: u
    }, t !== null && Pu(e, null), ts(), Cr(e), t !== null && ma(t, e, a, !0), e.childLanes = n, null;
  }
  function vi(t, e) {
    return e = gi(
      { mode: e.mode, children: e.children },
      t.mode
    ), e.ref = t.ref, t.child = e, e.return = t, e;
  }
  function Od(t, e, l) {
    return ba(e, t.child, null, l), t = vi(e, e.pendingProps), t.flags |= 2, ze(e), e.memoizedState = null, t;
  }
  function Ty(t, e, l) {
    var a = e.pendingProps, n = (e.flags & 128) !== 0;
    if (e.flags &= -129, t === null) {
      if (ot) {
        if (a.mode === "hidden")
          return t = vi(e, a), e.lanes = 536870912, t.memoizedState = { baseLanes: 0, cachePool: null }, Wn(null, t);
        if (ls(e), (t = Mt) ? (t = eh(
          t,
          Xe
        ), t = t !== null && t.data === "&" ? t : null, t !== null && (e.memoizedState = {
          dehydrated: t,
          treeContext: Dl !== null ? { id: el, overflow: ll } : null,
          retryLane: 536870912,
          hydrationErrors: null
        }, l = dr(t), l.return = e, e.child = l, It = e, Mt = null)) : t = null, t === null) throw wl(e);
        return e.lanes = 536870912, null;
      }
      return vi(e, a);
    }
    var u = t.memoizedState;
    if (u !== null) {
      var i = u.dehydrated;
      if (ls(e), n)
        if (e.flags & 256)
          e.flags &= -257, e = Od(
            t,
            e,
            l
          );
        else if (e.memoizedState !== null)
          e.child = t.child, e.flags |= 128, e = null;
        else throw Error(o(558));
      else if (kt || ma(t, e, l, !1), n = (l & t.childLanes) !== 0, kt || n) {
        if (Xl.current === null) {
          if (a = At, a !== null && (i = yo(a, l), i !== 0 && i !== u.retryLane))
            throw u.retryLane = i, fa(t, i), xe(a, t, i), Ns;
          Hi();
        }
        e = Od(
          t,
          e,
          l
        );
      } else
        t = u.treeContext, Mt = Qe(i.nextSibling), It = e, ot = !0, Ul = null, Xe = !1, t !== null && yr(e, t), e = vi(e, a), e.flags |= 134221824;
      return e;
    }
    return t = pl(t.child, {
      mode: a.mode,
      children: a.children
    }), t.ref = e.ref, e.child = t, t.return = e, t;
  }
  function Wa(t, e) {
    var l = e.ref;
    if (l === null)
      t !== null && t.ref !== null && (e.flags |= 4194816);
    else {
      if (typeof l != "function" && typeof l != "object")
        throw Error(o(284));
      (t === null || t.ref !== l) && (e.flags |= 4194816);
    }
  }
  function Ts(t, e, l, a, n) {
    return ha(e), l = us(
      t,
      e,
      l,
      a,
      void 0,
      n
    ), a = is(), t !== null && !kt ? (cs(t, e, n), Tl(t, e, n)) : (ot && a && Ju(e), e.flags |= 1, Ft(t, e, l, n), e.child);
  }
  function Md(t, e, l, a, n, u) {
    return ha(e), e.updateQueue = null, l = Dr(
      e,
      a,
      l,
      n
    ), Rr(t), a = is(), t !== null && !kt ? (cs(t, e, u), Tl(t, e, u)) : (ot && a && Ju(e), e.flags |= 1, Ft(t, e, l, u), e.child);
  }
  function Cd(t, e, l, a, n) {
    if (ha(e), e.stateNode === null) {
      var u = Xa, i = l.contextType;
      typeof i == "object" && i !== null && (u = ae(i)), u = new l(a, u), e.memoizedState = u.state !== null && u.state !== void 0 ? u.state : null, u.updater = Ss, e.stateNode = u, u._reactInternals = e, u = e.stateNode, u.props = a, u.state = e.memoizedState, u.refs = {}, Fc(e), i = l.contextType, u.context = typeof i == "object" && i !== null ? ae(i) : Xa, u.state = e.memoizedState, i = l.getDerivedStateFromProps, typeof i == "function" && (xs(
        e,
        l,
        i,
        a
      ), u.state = e.memoizedState), typeof l.getDerivedStateFromProps == "function" || typeof u.getSnapshotBeforeUpdate == "function" || typeof u.UNSAFE_componentWillMount != "function" && typeof u.componentWillMount != "function" || (i = u.state, typeof u.componentWillMount == "function" && u.componentWillMount(), typeof u.UNSAFE_componentWillMount == "function" && u.UNSAFE_componentWillMount(), i !== u.state && Ss.enqueueReplaceState(u, u.state, null), Kn(e, a, u, n), Zn(), u.state = e.memoizedState), typeof u.componentDidMount == "function" && (e.flags |= 4194308), a = !0;
    } else if (t === null) {
      u = e.stateNode;
      var f = e.memoizedProps, m = Sa(l, f);
      u.props = m;
      var x = u.context, j = l.contextType;
      i = Xa, typeof j == "object" && j !== null && (i = ae(j));
      var C = l.getDerivedStateFromProps;
      j = typeof C == "function" || typeof u.getSnapshotBeforeUpdate == "function", f = e.pendingProps !== f, j || typeof u.UNSAFE_componentWillReceiveProps != "function" && typeof u.componentWillReceiveProps != "function" || (f || x !== i) && gd(
        e,
        u,
        a,
        i
      ), ql = !1;
      var g = e.memoizedState;
      u.state = g, Kn(e, a, u, n), Zn(), x = e.memoizedState, f || g !== x || ql ? (typeof C == "function" && (xs(
        e,
        l,
        C,
        a
      ), x = e.memoizedState), (m = ql || vd(
        e,
        l,
        m,
        a,
        g,
        x,
        i
      )) ? (j || typeof u.UNSAFE_componentWillMount != "function" && typeof u.componentWillMount != "function" || (typeof u.componentWillMount == "function" && u.componentWillMount(), typeof u.UNSAFE_componentWillMount == "function" && u.UNSAFE_componentWillMount()), typeof u.componentDidMount == "function" && (e.flags |= 4194308)) : (typeof u.componentDidMount == "function" && (e.flags |= 4194308), e.memoizedProps = a, e.memoizedState = x), u.props = a, u.state = x, u.context = i, a = m) : (typeof u.componentDidMount == "function" && (e.flags |= 4194308), a = !1);
    } else {
      u = e.stateNode, Wc(t, e), i = e.memoizedProps, j = Sa(l, i), u.props = j, C = e.pendingProps, g = u.context, x = l.contextType, m = Xa, typeof x == "object" && x !== null && (m = ae(x)), f = l.getDerivedStateFromProps, (x = typeof f == "function" || typeof u.getSnapshotBeforeUpdate == "function") || typeof u.UNSAFE_componentWillReceiveProps != "function" && typeof u.componentWillReceiveProps != "function" || (i !== C || g !== m) && gd(
        e,
        u,
        a,
        m
      ), ql = !1, g = e.memoizedState, u.state = g, Kn(e, a, u, n), Zn();
      var T = e.memoizedState;
      i !== C || g !== T || ql || t !== null && t.dependencies !== null && Wu(t.dependencies) ? (typeof f == "function" && (xs(
        e,
        l,
        f,
        a
      ), T = e.memoizedState), (j = ql || vd(
        e,
        l,
        j,
        a,
        g,
        T,
        m
      ) || t !== null && t.dependencies !== null && Wu(t.dependencies)) ? (x || typeof u.UNSAFE_componentWillUpdate != "function" && typeof u.componentWillUpdate != "function" || (typeof u.componentWillUpdate == "function" && u.componentWillUpdate(a, T, m), typeof u.UNSAFE_componentWillUpdate == "function" && u.UNSAFE_componentWillUpdate(
        a,
        T,
        m
      )), typeof u.componentDidUpdate == "function" && (e.flags |= 4), typeof u.getSnapshotBeforeUpdate == "function" && (e.flags |= 1024)) : (typeof u.componentDidUpdate != "function" || i === t.memoizedProps && g === t.memoizedState || (e.flags |= 4), typeof u.getSnapshotBeforeUpdate != "function" || i === t.memoizedProps && g === t.memoizedState || (e.flags |= 1024), e.memoizedProps = a, e.memoizedState = T), u.props = a, u.state = T, u.context = m, a = j) : (typeof u.componentDidUpdate != "function" || i === t.memoizedProps && g === t.memoizedState || (e.flags |= 4), typeof u.getSnapshotBeforeUpdate != "function" || i === t.memoizedProps && g === t.memoizedState || (e.flags |= 1024), a = !1);
    }
    return u = a, Wa(t, e), a = (e.flags & 128) !== 0, u || a ? (u = e.stateNode, l = a && typeof l.getDerivedStateFromError != "function" ? null : u.render(), e.flags |= 1, t !== null && a ? (e.child = ba(
      e,
      t.child,
      null,
      n
    ), e.child = ba(
      e,
      null,
      l,
      n
    )) : Ft(t, e, l, n), e.memoizedState = u.state, t = e.child) : t = Tl(
      t,
      e,
      n
    ), t;
  }
  function Rd(t, e, l, a) {
    return ra(), e.flags |= 256, Ft(t, e, l, a), e.child;
  }
  var Es = {
    dehydrated: null,
    treeContext: null,
    retryLane: 0,
    hydrationErrors: null
  };
  function js(t) {
    return { baseLanes: t, cachePool: Sr() };
  }
  function zs(t, e, l) {
    return t = t !== null ? t.childLanes & ~l : 0, e && (t |= Me), t;
  }
  function Dd(t, e, l) {
    var a = e.pendingProps, n = !1, u = (e.flags & 128) !== 0, i;
    if ((i = u) || (i = t !== null && t.memoizedState === null ? !1 : (ue.current & 2) !== 0), i && (n = !0, e.flags &= -129), i = (e.flags & 32) !== 0, e.flags &= -33, t === null) {
      if (ot) {
        if (n ? Gl(e) : Ql(), (t = Mt) ? (t = eh(
          t,
          Xe
        ), t = t !== null && t.data !== "&" ? t : null, t !== null && (e.memoizedState = {
          dehydrated: t,
          treeContext: Dl !== null ? { id: el, overflow: ll } : null,
          retryLane: 536870912,
          hydrationErrors: null
        }, l = dr(t), l.return = e, e.child = l, It = e, Mt = null)) : t = null, t === null) throw wl(e);
        return zf(t) ? e.lanes = 32 : e.lanes = 536870912, null;
      }
      return u = a.children, a = a.fallback, n ? (Ql(), n = e.mode, u = gi(
        { mode: "hidden", children: u },
        n
      ), a = oa(
        a,
        n,
        l,
        null
      ), u.return = e, a.return = e, u.sibling = a, e.child = u, a = e.child, a.memoizedState = js(l), a.childLanes = zs(
        t,
        i,
        l
      ), e.memoizedState = Es, Wn(null, a)) : (Gl(e), As(e, u));
    }
    var f = t.memoizedState;
    if (f !== null) {
      var m = f.dehydrated;
      if (m !== null)
        return Ey(
          t,
          e,
          u,
          i,
          a,
          m,
          f,
          l
        );
    }
    return n ? (Ql(), n = a.fallback, u = e.mode, f = t.child, m = f.sibling, a = pl(f, {
      mode: "hidden",
      children: a.children
    }), a.subtreeFlags = f.subtreeFlags & 1206910976, m !== null ? n = pl(m, n) : (n = oa(
      n,
      u,
      l,
      null
    ), n.flags |= 2), n.return = e, a.return = e, a.sibling = n, e.child = a, Wn(null, a), a = e.child, n = t.child.memoizedState, n === null ? n = js(l) : (u = n.cachePool, u !== null ? (f = Zt._currentValue, u = u.parent !== f ? { parent: f, pool: f } : u) : u = Sr(), n = {
      baseLanes: n.baseLanes | l,
      cachePool: u
    }), a.memoizedState = n, a.childLanes = zs(
      t,
      i,
      l
    ), e.memoizedState = Es, Wn(t.child, a)) : (Gl(e), l = t.child, t = l.sibling, l = pl(l, {
      mode: "visible",
      children: a.children
    }), l.return = e, l.sibling = null, t !== null && (i = e.deletions, i === null ? (e.deletions = [t], e.flags |= 16) : i.push(t)), e.child = l, e.memoizedState = null, l);
  }
  function As(t, e) {
    return e = gi(
      { mode: "visible", children: e },
      t.mode
    ), e.return = t, t.child = e;
  }
  function gi(t, e) {
    return t = ve(22, t, null, e), t.lanes = 0, t;
  }
  function pi(t, e, l) {
    return ba(e, t.child, null, l), t = As(
      e,
      e.pendingProps.children
    ), t.flags |= 2, e.memoizedState = null, t;
  }
  function Ey(t, e, l, a, n, u, i, f) {
    if (l)
      return e.flags & 256 ? (Gl(e), e.flags &= -257, pi(
        t,
        e,
        f
      )) : e.memoizedState !== null ? (Ql(), e.child = t.child, e.flags |= 128, null) : (Ql(), u = n.fallback, i = e.mode, n = gi(
        { mode: "visible", children: n.children },
        i
      ), u = oa(
        u,
        i,
        f,
        null
      ), u.flags |= 2, n.return = e, u.return = e, n.sibling = u, e.child = n, ba(e, t.child, null, f), n = e.child, n.memoizedState = js(f), n.childLanes = zs(
        t,
        a,
        f
      ), e.memoizedState = Es, Wn(null, n));
    if (Gl(e), zf(u)) {
      if (a = u.nextSibling && u.nextSibling.dataset, a) var m = a.dgst;
      return a = m, a !== "" && (n = Error(o(419)), n.stack = "", n.digest = a, Yn({ value: n, source: null, stack: null })), pi(
        t,
        e,
        f
      );
    }
    if (kt || ma(t, e, f, !1), a = (f & t.childLanes) !== 0, kt || a) {
      if (Xl.current !== null)
        return pi(
          t,
          e,
          f
        );
      if (a = At, a !== null && (n = yo(
        a,
        f
      ), n !== 0 && n !== i.retryLane))
        throw i.retryLane = n, fa(t, n), xe(a, t, n), Ns;
      return jf(u) || Hi(), pi(
        t,
        e,
        f
      );
    }
    return jf(u) ? (e.flags |= 192, e.child = t.child, null) : (t = i.treeContext, Mt = Qe(u.nextSibling), It = e, ot = !0, Ul = null, Xe = !1, t !== null && yr(e, t), e = As(
      e,
      n.children
    ), e.flags |= 134221824, e);
  }
  function Ud(t, e, l) {
    t.lanes |= e;
    var a = t.alternate;
    a !== null && (a.lanes |= e), Fu(t.return, e, l);
  }
  function wd(t) {
    for (var e = null; t !== null; ) {
      var l = t.alternate;
      l !== null && ui(l) === null && (e = t), t = t.sibling;
    }
    return e;
  }
  function bi(t, e, l, a, n, u) {
    var i = t.memoizedState;
    i === null ? t.memoizedState = {
      isBackwards: e,
      rendering: null,
      renderingStartTime: 0,
      last: a,
      tail: l,
      tailMode: n,
      treeForkCount: u
    } : (i.isBackwards = e, i.rendering = null, i.renderingStartTime = 0, i.last = a, i.tail = l, i.tailMode = n, i.treeForkCount = u);
  }
  function Os(t) {
    var e = t.child;
    for (t.child = null; e !== null; ) {
      var l = e.sibling;
      e.sibling = t.child, t.child = e, e = l;
    }
  }
  function Ms(t, e, l) {
    var a = e.pendingProps, n = a.revealOrder, u = a.tail;
    a = a.children;
    var i = ue.current;
    if (e.flags & 128)
      return kn(e, i), null;
    var f = (i & 2) !== 0;
    if (f ? (i = i & 1 | 2, e.flags |= 128) : i &= 1, kn(e, i), n === "backwards" && t !== null ? (Os(t), Ft(t, e, a, l), Os(t)) : Ft(t, e, a, l), a = ot ? qn : 0, !f && t !== null && (t.flags & 128) !== 0)
      t: for (t = e.child; t !== null; ) {
        if (t.tag === 13)
          t.memoizedState !== null && Ud(t, l, e);
        else if (t.tag === 19)
          Ud(t, l, e);
        else if (t.child !== null) {
          t.child.return = t, t = t.child;
          continue;
        }
        if (t === e) break t;
        for (; t.sibling === null; ) {
          if (t.return === null || t.return === e)
            break t;
          t = t.return;
        }
        t.sibling.return = t.return, t = t.sibling;
      }
    switch (n) {
      case "backwards":
        l = wd(e.child), l === null ? (n = e.child, e.child = null) : (n = l.sibling, l.sibling = null, Os(e)), bi(
          e,
          !0,
          n,
          null,
          u,
          a
        );
        break;
      case "unstable_legacy-backwards":
        for (l = null, n = e.child, e.child = null; n !== null; ) {
          if (t = n.alternate, t !== null && ui(t) === null) {
            e.child = n;
            break;
          }
          t = n.sibling, n.sibling = l, l = n, n = t;
        }
        bi(
          e,
          !0,
          l,
          null,
          u,
          a
        );
        break;
      case "together":
        bi(
          e,
          !1,
          null,
          null,
          void 0,
          a
        );
        break;
      case "independent":
        e.memoizedState = null;
        break;
      default:
        l = wd(e.child), l === null ? (n = e.child, e.child = null) : (n = l.sibling, l.sibling = null), bi(
          e,
          !1,
          n,
          l,
          u,
          a
        );
    }
    return e.child;
  }
  function Hd(t, e, l) {
    var a = e.pendingProps;
    return Hl(e, e.type, a.value), Ft(t, e, a.children, l), e.child;
  }
  function Tl(t, e, l) {
    if (t !== null && (e.dependencies = t.dependencies), kl |= e.lanes, (l & e.childLanes) === 0)
      if (t !== null) {
        if (ma(
          t,
          e,
          l,
          !1
        ), (l & e.childLanes) === 0)
          return null;
      } else return null;
    if (t !== null && e.child !== t.child)
      throw Error(o(153));
    if (e.child !== null) {
      for (t = e.child, l = pl(t, t.pendingProps), e.child = l, l.return = e; t.sibling !== null; )
        t = t.sibling, l = l.sibling = pl(t, t.pendingProps), l.return = e;
      l.sibling = null;
    }
    return e.child;
  }
  function Cs(t, e) {
    return (t.lanes & e) !== 0 ? !0 : (t = t.dependencies, !!(t !== null && Wu(t)));
  }
  function jy(t, e, l) {
    switch (e.tag) {
      case 3:
        Tu(e, e.stateNode.containerInfo), Hl(e, Zt, t.memoizedState.cache), ra();
        break;
      case 27:
      case 5:
        nc(e);
        break;
      case 4:
        Tu(e, e.stateNode.containerInfo);
        break;
      case 10:
        Hl(
          e,
          e.type,
          e.memoizedProps.value
        );
        break;
      case 31:
        if (e.memoizedState !== null)
          return e.flags |= 128, ls(e), null;
        break;
      case 13:
        var a = e.memoizedState;
        if (a !== null) {
          if (a.dehydrated !== null)
            return Gl(e), e.flags |= 128, null;
          a = ma(
            t,
            e,
            l,
            !1
          );
          var n = e.child.childLanes;
          return a || (l & n) !== 0 ? Dd(t, e, l) : (Gl(e), t = Tl(
            t,
            e,
            l
          ), t !== null ? t.sibling : null);
        }
        Gl(e);
        break;
      case 19:
        if (e.flags & 128)
          return Ms(
            t,
            e,
            l
          );
        if (n = (t.flags & 128) !== 0, a = (l & e.childLanes) !== 0, a || (ma(
          t,
          e,
          l,
          !1
        ), a = (l & e.childLanes) !== 0), n) {
          if (a)
            return Ms(
              t,
              e,
              l
            );
          e.flags |= 128;
        }
        if (n = e.memoizedState, n !== null && (n.rendering = null, n.tail = null, n.lastEffect = null), kn(e, ue.current), a) break;
        return null;
      case 22:
        return e.lanes = 0, zd(
          t,
          e,
          l,
          e.pendingProps
        );
      case 24:
        Hl(e, Zt, t.memoizedState.cache);
    }
    return Tl(t, e, l);
  }
  function Bd(t, e, l) {
    if (t !== null)
      if (t.memoizedProps !== e.pendingProps)
        kt = !0;
      else {
        if (!Cs(t, l) && (e.flags & 128) === 0)
          return kt = !1, jy(
            t,
            e,
            l
          );
        kt = (t.flags & 131072) !== 0;
      }
    else
      kt = !1, ot && (e.flags & 1048576) !== 0 && hr(e, qn, e.index);
    switch (e.lanes = 0, e.tag) {
      case 16:
        t: {
          var a = e.pendingProps;
          if (t = ga(e.elementType), e.type = t, typeof t == "function")
            qc(t) ? (a = Sa(t, a), e.tag = 1, e = Cd(
              null,
              e,
              t,
              a,
              l
            )) : (e.tag = 0, e = Ts(
              null,
              e,
              t,
              a,
              l
            ));
          else {
            if (t != null) {
              var n = t.$$typeof;
              if (n === X) {
                e.tag = 11, e = Td(
                  null,
                  e,
                  t,
                  a,
                  l
                );
                break t;
              } else if (n === pt) {
                e.tag = 14, e = Ed(
                  null,
                  e,
                  t,
                  a,
                  l
                );
                break t;
              } else if (n === Rt) {
                e.tag = 10, e.type = t, e = Hd(
                  null,
                  e,
                  l
                );
                break t;
              }
            }
            throw e = K(t) || t, Error(o(306, e, ""));
          }
        }
        return e;
      case 0:
        return Ts(
          t,
          e,
          e.type,
          e.pendingProps,
          l
        );
      case 1:
        return a = e.type, n = Sa(
          a,
          e.pendingProps
        ), Cd(
          t,
          e,
          a,
          n,
          l
        );
      case 3:
        t: {
          if (Tu(
            e,
            e.stateNode.containerInfo
          ), t === null) throw Error(o(387));
          a = e.pendingProps;
          var u = e.memoizedState;
          n = u.element, Wc(t, e), Kn(e, a, null, l);
          var i = e.memoizedState;
          if (a = i.cache, Hl(e, Zt, a), a !== u.cache && Zc(
            e,
            [Zt],
            l,
            !0
          ), Zn(), a = i.element, u.isDehydrated)
            if (u = {
              element: a,
              isDehydrated: !1,
              cache: i.cache
            }, e.updateQueue.baseState = u, e.memoizedState = u, e.flags & 256) {
              e = Rd(
                t,
                e,
                a,
                l
              );
              break t;
            } else if (a !== n) {
              n = qe(
                Error(o(424)),
                e
              ), Yn(n), e = Rd(
                t,
                e,
                a,
                l
              );
              break t;
            } else
              for (t = e.stateNode.containerInfo, t.nodeType === 9 ? t = t.body : t = t.nodeName === "HTML" ? t.ownerDocument.body : t, Mt = Qe(t.firstChild), It = e, ot = !0, Ul = null, Xe = !0, l = zr(
                e,
                null,
                a,
                l
              ), e.child = l; l; )
                l.flags = l.flags & -3 | 134221824, l = l.sibling;
          else {
            if (ra(), a === n) {
              e = Tl(
                t,
                e,
                l
              );
              break t;
            }
            Ft(t, e, a, l);
          }
          e = e.child;
        }
        return e;
      case 26:
        return Wa(t, e), t === null ? (l = sh(
          e.type,
          null,
          e.pendingProps,
          null
        )) ? e.memoizedState = l : ot || (e.stateNode = Xm(
          e.type,
          e.pendingProps,
          Al.current,
          e
        )) : e.memoizedState = sh(
          e.type,
          t.memoizedProps,
          e.pendingProps,
          t.memoizedState
        ), null;
      case 27:
        return nc(e), t === null && ot && (a = e.stateNode = nh(
          e.type,
          e.pendingProps,
          Al.current
        ), It = e, Xe = !0, n = Mt, Wl(e.type) ? (Af = n, Mt = Qe(a.firstChild)) : Mt = n), Ft(
          t,
          e,
          e.pendingProps.children,
          l
        ), Wa(t, e), t === null && (e.flags |= 4194304), e.child;
      case 5:
        return t === null && ot && ((n = a = Mt) && (a = xv(
          a,
          e.type,
          e.pendingProps,
          Xe
        ), a !== null ? (e.stateNode = a, It = e, Mt = Qe(a.firstChild), Xe = !1, n = !0) : n = !1), n || wl(e)), nc(e), n = e.type, u = e.pendingProps, i = t !== null ? t.memoizedProps : null, a = u.children, bf(n, u) ? a = null : i !== null && bf(n, i) && (e.flags |= 32), e.memoizedState !== null && (n = us(
          t,
          e,
          yy,
          null,
          null,
          l
        ), vn._currentValue = n), Wa(t, e), Ft(t, e, a, l), e.child;
      case 6:
        return t === null && ot && ((t = l = Mt) && (l = Sv(
          l,
          e.pendingProps,
          Xe
        ), l !== null ? (e.stateNode = l, It = e, Mt = null, t = !0) : t = !1), t || wl(e)), null;
      case 13:
        return Dd(t, e, l);
      case 4:
        return Tu(
          e,
          e.stateNode.containerInfo
        ), a = e.pendingProps, t === null ? e.child = ba(
          e,
          null,
          a,
          l
        ) : Ft(t, e, a, l), e.child;
      case 11:
        return Td(
          t,
          e,
          e.type,
          e.pendingProps,
          l
        );
      case 7:
        return a = e.pendingProps, Wa(t, e), Ft(t, e, a, l), e.child;
      case 8:
        return Ft(
          t,
          e,
          e.pendingProps.children,
          l
        ), e.child;
      case 12:
        return Ft(
          t,
          e,
          e.pendingProps.children,
          l
        ), e.child;
      case 10:
        return Hd(t, e, l);
      case 9:
        return n = e.type._context, a = e.pendingProps.children, ha(e), n = ae(n), a = a(n), e.flags |= 1, Ft(t, e, a, l), e.child;
      case 14:
        return Ed(
          t,
          e,
          e.type,
          e.pendingProps,
          l
        );
      case 15:
        return jd(
          t,
          e,
          e.type,
          e.pendingProps,
          l
        );
      case 19:
        return Ms(t, e, l);
      case 31:
        return Ty(t, e, l);
      case 22:
        return zd(
          t,
          e,
          l,
          e.pendingProps
        );
      case 24:
        return ha(e), a = ae(Zt), t === null ? (n = Jc(), n === null && (n = At, u = Kc(), n.pooledCache = u, u.refCount++, u !== null && (n.pooledCacheLanes |= l), n = u), e.memoizedState = { parent: a, cache: n }, Fc(e), Hl(e, Zt, n)) : ((t.lanes & l) !== 0 && (Wc(t, e), Kn(e, null, null, l), Zn()), n = t.memoizedState, u = e.memoizedState, n.parent !== a ? (n = { parent: a, cache: a }, e.memoizedState = n, e.lanes === 0 && (e.memoizedState = e.updateQueue.baseState = n), Hl(e, Zt, a)) : (a = u.cache, Hl(e, Zt, a), a !== n.cache && Zc(
          e,
          [Zt],
          l,
          !0
        ))), Ft(
          t,
          e,
          e.pendingProps.children,
          l
        ), e.child;
      case 30:
        return e.stateNode === null && (e.stateNode = {
          autoName: null,
          paired: null,
          clones: null,
          ref: null
        }), a = e.pendingProps, a.name != null && a.name !== "auto" ? e.flags |= t === null ? 18882560 : 18874368 : ot && Ju(e), t !== null && t.memoizedProps.name !== a.name ? e.flags |= 4194816 : Wa(t, e), Ft(t, e, a.children, l), e.child;
      case 29:
        throw e.pendingProps;
    }
    throw Error(o(156, e.tag));
  }
  function El(t) {
    t.flags |= 4;
  }
  function Rs(t, e, l, a, n) {
    var u;
    if ((u = (t.mode & 32) !== 0) && (u = l === null ? dh(e, a) : dh(e, a) && (a.src !== l.src || a.srcSet !== l.srcSet)), u) {
      if (t.flags |= 16777216, (n & 335544128) === n)
        if (t.stateNode.complete) t.flags |= 8192;
        else if (pm()) t.flags |= 8192;
        else
          throw pa = ei, $c;
    } else t.flags &= -16777217;
  }
  function qd(t, e) {
    if (e.type !== "stylesheet" || (e.state.loading & 4) !== 0)
      t.flags &= -16777217;
    else if (t.flags |= 16777216, !mh(e))
      if (pm()) t.flags |= 8192;
      else
        throw pa = ei, $c;
  }
  function xi(t, e) {
    e !== null && (t.flags |= 4), t.flags & 16384 && (e = t.tag !== 22 ? ro() : 536870912, t.lanes |= e, ln |= e);
  }
  function In(t, e) {
    if (!ot)
      switch (t.tailMode) {
        case "visible":
          break;
        case "collapsed":
          for (var l = t.tail, a = null; l !== null; )
            l.alternate !== null && (a = l), l = l.sibling;
          a === null ? e || t.tail === null ? t.tail = null : t.tail.sibling = null : a.sibling = null;
          break;
        default:
          for (e = t.tail, l = null; e !== null; )
            e.alternate !== null && (l = e), e = e.sibling;
          l === null ? t.tail = null : l.sibling = null;
      }
  }
  function Ct(t) {
    var e = t.alternate !== null && t.alternate.child === t.child, l = 0, a = 0;
    if (e)
      for (var n = t.child; n !== null; )
        l |= n.lanes | n.childLanes, a |= n.subtreeFlags & 1206910976, a |= n.flags & 1206910976, n.return = t, n = n.sibling;
    else
      for (n = t.child; n !== null; )
        l |= n.lanes | n.childLanes, a |= n.subtreeFlags, a |= n.flags, n.return = t, n = n.sibling;
    return t.subtreeFlags |= a, t.childLanes = l, e;
  }
  function zy(t, e, l) {
    var a = e.pendingProps;
    switch (Xc(e), e.tag) {
      case 16:
      case 15:
      case 0:
      case 11:
      case 7:
      case 8:
      case 12:
      case 9:
      case 14:
        return Ct(e), null;
      case 1:
        return Ct(e), null;
      case 3:
        return l = e.stateNode, a = null, t !== null && (a = t.memoizedState.cache), e.memoizedState.cache !== a && (e.flags |= 2048), Sl(Zt), Aa(), l.pendingContext && (l.context = l.pendingContext, l.pendingContext = null), (t === null || t.child === null) && (Va(e) ? El(e) : t === null || t.memoizedState.isDehydrated && (e.flags & 256) === 0 || (e.flags |= 1024, Qc())), Ct(e), null;
      case 26:
        var n = e.type, u = e.memoizedState;
        return t === null ? (El(e), u !== null ? (Ct(e), qd(e, u)) : (Ct(e), Rs(
          e,
          n,
          null,
          a,
          l
        ))) : u ? u !== t.memoizedState ? (El(e), Ct(e), qd(e, u)) : (Ct(e), e.flags &= -16777217) : (t = t.memoizedProps, t !== a && El(e), Ct(e), Rs(
          e,
          n,
          t,
          a,
          l
        )), null;
      case 27:
        if (Eu(e), l = Al.current, n = e.type, t !== null && e.stateNode != null)
          t.memoizedProps !== a && El(e);
        else {
          if (!a) {
            if (e.stateNode === null)
              throw Error(o(166));
            return Ct(e), e.subtreeFlags &= -33554433, null;
          }
          t = Pe.current, Va(e) ? vr(e) : (t = nh(n, a, l), e.stateNode = t, El(e));
        }
        return Ct(e), e.subtreeFlags &= -33554433, null;
      case 5:
        if (Eu(e), n = e.type, t !== null && e.stateNode != null)
          t.memoizedProps !== a && El(e);
        else {
          if (!a) {
            if (e.stateNode === null)
              throw Error(o(166));
            return Ct(e), e.subtreeFlags &= -33554433, null;
          }
          if (u = Pe.current, Va(e))
            vr(e);
          else {
            var i = fu(
              Al.current
            );
            switch (u) {
              case 1:
                u = i.createElementNS(
                  "http://www.w3.org/2000/svg",
                  n
                );
                break;
              case 2:
                u = i.createElementNS(
                  "http://www.w3.org/1998/Math/MathML",
                  n
                );
                break;
              default:
                switch (n) {
                  case "svg":
                    u = i.createElementNS(
                      "http://www.w3.org/2000/svg",
                      n
                    );
                    break;
                  case "math":
                    u = i.createElementNS(
                      "http://www.w3.org/1998/Math/MathML",
                      n
                    );
                    break;
                  case "script":
                    u = i.createElement("div"), u.innerHTML = "<script><\/script>", u = u.removeChild(
                      u.firstChild
                    );
                    break;
                  case "select":
                    u = typeof a.is == "string" ? i.createElement("select", {
                      is: a.is
                    }) : i.createElement("select"), a.multiple ? u.multiple = !0 : a.size && (u.size = a.size);
                    break;
                  default:
                    u = typeof a.is == "string" ? i.createElement(n, { is: a.is }) : i.createElement(n);
                }
            }
            u[le] = e, u[ye] = a;
            t: for (i = e.child; i !== null; ) {
              if (i.tag === 5 || i.tag === 6)
                u.appendChild(i.stateNode);
              else if (i.tag !== 4 && i.tag !== 27 && i.child !== null) {
                i.child.return = i, i = i.child;
                continue;
              }
              if (i === e) break t;
              for (; i.sibling === null; ) {
                if (i.return === null || i.return === e)
                  break t;
                i = i.return;
              }
              i.sibling.return = i.return, i = i.sibling;
            }
            e.stateNode = u;
            t: switch (ce(u, n, a), n) {
              case "button":
              case "input":
              case "select":
              case "textarea":
                a = !!a.autoFocus;
                break t;
              case "img":
                a = !0;
                break t;
              default:
                a = !1;
            }
            a && El(e);
          }
        }
        return Ct(e), e.subtreeFlags &= -33554433, Rs(
          e,
          e.type,
          t === null ? null : t.memoizedProps,
          e.pendingProps,
          l
        ), null;
      case 6:
        if (t && e.stateNode != null)
          t.memoizedProps !== a && El(e);
        else {
          if (typeof a != "string" && e.stateNode === null)
            throw Error(o(166));
          if (t = Al.current, Va(e)) {
            if (t = e.stateNode, l = e.memoizedProps, a = null, n = It, n !== null)
              switch (n.tag) {
                case 27:
                case 5:
                  a = n.memoizedProps;
              }
            t[le] = e, t = !!(t.nodeValue === l || a !== null && a.suppressHydrationWarning === !0 || Bm(t.nodeValue, l)), t || wl(e, !0);
          } else
            t = fu(t).createTextNode(
              a
            ), t[le] = e, e.stateNode = t;
        }
        return Ct(e), null;
      case 31:
        if (l = e.memoizedState, t === null || t.memoizedState !== null) {
          if (a = Va(e), l !== null) {
            if (t === null) {
              if (!a) throw Error(o(318));
              if (t = e.memoizedState, t = t !== null ? t.dehydrated : null, !t) throw Error(o(557));
              t[le] = e;
            } else
              ra(), (e.flags & 128) === 0 && (e.memoizedState = null), e.flags |= 4;
            Ct(e), t = !1;
          } else
            l = Qc(), t !== null && t.memoizedState !== null && (t.memoizedState.hydrationErrors = l), t = !0;
          if (!t)
            return e.flags & 256 ? (ze(e), e) : (ze(e), null);
          if ((e.flags & 128) !== 0)
            throw Error(o(558));
        }
        return Ct(e), null;
      case 13:
        if (a = e.memoizedState, t === null || t.memoizedState !== null && t.memoizedState.dehydrated !== null) {
          if (n = Va(e), a !== null && a.dehydrated !== null) {
            if (t === null) {
              if (!n) throw Error(o(318));
              if (n = e.memoizedState, n = n !== null ? n.dehydrated : null, !n) throw Error(o(317));
              n[le] = e;
            } else
              ra(), (e.flags & 128) === 0 && (e.memoizedState = null), e.flags |= 4;
            Ct(e), n = !1;
          } else
            n = Qc(), t !== null && t.memoizedState !== null && (t.memoizedState.hydrationErrors = n), n = !0;
          if (!n)
            return e.flags & 256 ? (ze(e), e) : (ze(e), null);
        }
        return ze(e), (e.flags & 128) !== 0 ? (e.lanes = l, e) : (l = a !== null, t = t !== null && t.memoizedState !== null, l && (a = e.child, n = null, a.alternate !== null && a.alternate.memoizedState !== null && a.alternate.memoizedState.cachePool !== null && (n = a.alternate.memoizedState.cachePool.pool), u = null, a.memoizedState !== null && a.memoizedState.cachePool !== null && (u = a.memoizedState.cachePool.pool), u !== n && (a.flags |= 2048)), l !== t && l && (e.child.flags |= 8192), xi(e, e.updateQueue), Ct(e), null);
      case 4:
        return Aa(), t === null && hf(e.stateNode.containerInfo), e.flags |= 67108864, Ct(e), null;
      case 10:
        return Sl(e.type), Ct(e), null;
      case 19:
        if (as(e), a = e.memoizedState, a === null) return Ct(e), null;
        if (n = (e.flags & 128) !== 0, u = a.rendering, u === null)
          if (n) In(a, !1);
          else {
            if (Gt !== 0 || t !== null && (t.flags & 128) !== 0)
              for (t = e.child; t !== null; ) {
                if (u = ui(t), u !== null) {
                  for (e.flags |= 128, In(a, !1), t = u.updateQueue, e.updateQueue = t, xi(e, t), e.subtreeFlags = 0, t = l, l = e.child; l !== null; )
                    rr(l, t), l = l.sibling;
                  return kn(
                    e,
                    ue.current & 1 | 2
                  ), ot && bl(e, a.treeForkCount), e.child;
                }
                t = t.sibling;
              }
            a.tail !== null && _e() > Ri && (e.flags |= 128, n = !0, In(a, !1), e.lanes = 4194304);
          }
        else {
          if (!n)
            if (t = ui(u), t !== null) {
              if (e.flags |= 128, n = !0, t = t.updateQueue, e.updateQueue = t, xi(e, t), In(a, !0), a.tail === null && a.tailMode !== "collapsed" && a.tailMode !== "visible" && !u.alternate && !ot)
                return Ct(e), null;
            } else
              2 * _e() - a.renderingStartTime > Ri && l !== 536870912 && (e.flags |= 128, n = !0, In(a, !1), e.lanes = 4194304);
          a.isBackwards ? (u.sibling = e.child, e.child = u) : (t = a.last, t !== null ? t.sibling = u : e.child = u, a.last = u);
        }
        if (a.tail !== null) {
          t = a.tail;
          t: {
            for (l = t; l !== null; ) {
              if (l.alternate !== null) {
                l = !1;
                break t;
              }
              l = l.sibling;
            }
            l = !0;
          }
          return a.rendering = t, a.tail = t.sibling, a.renderingStartTime = _e(), t.sibling = null, u = ue.current, u = n ? u & 1 | 2 : u & 1, a.tailMode === "visible" || a.tailMode === "collapsed" || !l || ot ? kn(e, u) : (l = u, Ot(ne, e), Ot(ue, l), fe === null && (fe = e)), ot && bl(e, a.treeForkCount), t;
        }
        return Ct(e), null;
      case 22:
      case 23:
        return ze(e), es(), a = e.memoizedState !== null, t !== null ? t.memoizedState !== null !== a && (e.flags |= 8192) : a && (e.flags |= 8192), a ? (l & 536870912) !== 0 && (e.flags & 128) === 0 && (Ct(e), e.subtreeFlags & 6 && (e.flags |= 8192)) : Ct(e), l = e.updateQueue, l !== null && xi(e, l.retryQueue), l = null, t !== null && t.memoizedState !== null && t.memoizedState.cachePool !== null && (l = t.memoizedState.cachePool.pool), a = null, e.memoizedState !== null && e.memoizedState.cachePool !== null && (a = e.memoizedState.cachePool.pool), a !== l && (e.flags |= 2048), t !== null && Qt(va), null;
      case 24:
        return l = null, t !== null && (l = t.memoizedState.cache), e.memoizedState.cache !== l && (e.flags |= 2048), Sl(Zt), Ct(e), null;
      case 25:
        return null;
      case 30:
        return e.flags |= 33554432, Ct(e), null;
    }
    throw Error(o(156, e.tag));
  }
  function Ay(t, e) {
    switch (Xc(e), e.tag) {
      case 1:
        return t = e.flags, t & 65536 ? (e.flags = t & -65537 | 128, e) : null;
      case 3:
        return Sl(Zt), Aa(), t = e.flags, (t & 65536) !== 0 && (t & 128) === 0 ? (e.flags = t & -65537 | 128, e) : null;
      case 26:
      case 27:
      case 5:
        return Eu(e), null;
      case 31:
        if (e.memoizedState !== null) {
          if (ze(e), e.alternate === null)
            throw Error(o(340));
          ra();
        }
        return t = e.flags, t & 65536 ? (e.flags = t & -65537 | 128, e) : null;
      case 13:
        if (ze(e), t = e.memoizedState, t !== null && t.dehydrated !== null) {
          if (e.alternate === null)
            throw Error(o(340));
          ra();
        }
        return t = e.flags, t & 65536 ? (e.flags = t & -65537 | 128, e) : null;
      case 19:
        return as(e), t = e.flags, t & 65536 ? (e.flags = t & -65537 | 128, t = e.memoizedState, t !== null && (t.rendering = null, t.tail = null), e.flags |= 4, e) : null;
      case 4:
        return Aa(), null;
      case 10:
        return Sl(e.type), null;
      case 22:
      case 23:
        return ze(e), es(), t !== null && Qt(va), t = e.flags, t & 65536 ? (e.flags = t & -65537 | 128, e) : null;
      case 24:
        return Sl(Zt), null;
      case 25:
        return null;
      default:
        return null;
    }
  }
  function Yd(t, e) {
    switch (Xc(e), e.tag) {
      case 3:
        Sl(Zt), Aa();
        break;
      case 26:
      case 27:
      case 5:
        Eu(e);
        break;
      case 4:
        Aa();
        break;
      case 31:
        e.memoizedState !== null && ze(e);
        break;
      case 13:
        ze(e);
        break;
      case 19:
        as(e);
        break;
      case 10:
        Sl(e.type);
        break;
      case 22:
      case 23:
        ze(e), es(), t !== null && Qt(va);
        break;
      case 24:
        Sl(Zt);
    }
  }
  function Pn(t, e) {
    try {
      var l = e.updateQueue, a = l !== null ? l.lastEffect : null;
      if (a !== null) {
        var n = a.next;
        l = n;
        do {
          if ((l.tag & t) === t) {
            a = void 0;
            var u = l.create, i = l.inst;
            a = u(), i.destroy = a;
          }
          l = l.next;
        } while (l !== n);
      }
    } catch (f) {
      Et(e, e.return, f);
    }
  }
  function Vl(t, e, l) {
    try {
      var a = e.updateQueue, n = a !== null ? a.lastEffect : null;
      if (n !== null) {
        var u = n.next;
        a = u;
        do {
          if ((a.tag & t) === t) {
            var i = a.inst, f = i.destroy;
            if (f !== void 0) {
              i.destroy = void 0, n = e;
              var m = l, x = f;
              try {
                x();
              } catch (j) {
                Et(
                  n,
                  m,
                  j
                );
              }
            }
          }
          a = a.next;
        } while (a !== u);
      }
    } catch (j) {
      Et(e, e.return, j);
    }
  }
  function Ld(t) {
    var e = t.updateQueue;
    if (e !== null) {
      var l = t.stateNode;
      try {
        Or(e, l);
      } catch (a) {
        Et(t, t.return, a);
      }
    }
  }
  function Xd(t, e, l) {
    l.props = Sa(
      t.type,
      t.memoizedProps
    ), l.state = t.memoizedState;
    try {
      l.componentWillUnmount();
    } catch (a) {
      Et(t, e, a);
    }
  }
  function al(t, e) {
    try {
      var l = t.ref;
      if (l !== null) {
        switch (t.tag) {
          case 26:
          case 27:
          case 5:
            var a = t.stateNode;
            break;
          case 30:
            var n = t.stateNode, u = vl(t.memoizedProps, n);
            (n.ref === null || n.ref.name !== u) && (n.ref = Jm(u)), a = n.ref;
            break;
          case 7:
            if (t.stateNode === null) {
              var i = new Re(t);
              N(
                t.child,
                !1,
                pv,
                i,
                void 0,
                void 0
              ), t.stateNode = i;
            }
            a = t.stateNode;
            break;
          default:
            a = t.stateNode;
        }
        typeof l == "function" ? t.refCleanup = l(a) : l.current = a;
      }
    } catch (f) {
      Et(t, e, f);
    }
  }
  function ie(t, e) {
    var l = t.ref, a = t.refCleanup;
    if (l !== null)
      if (typeof a == "function")
        try {
          a();
        } catch (n) {
          Et(t, e, n);
        } finally {
          t.refCleanup = null, t = t.alternate, t != null && (t.refCleanup = null);
        }
      else if (typeof l == "function")
        try {
          l(null);
        } catch (n) {
          Et(t, e, n);
        }
      else l.current = null;
  }
  function Si(t, e) {
    if ((t.tag === 5 || t.tag === 27 || t.tag === 6) && t.alternate === null && e !== null)
      for (var l = 0; l < e.length; l++)
        th(
          t.stateNode,
          e[l]
        );
  }
  function Gd(t) {
    for (var e = t.return; e !== null && (Us(e) && th(t.stateNode, e.stateNode), !Ds(e)); )
      e = e.return;
  }
  function tu(t) {
    for (var e = t.return; e !== null && (Us(e) && bv(t.stateNode, e.stateNode), !Ds(e)); )
      e = e.return;
  }
  function Ds(t) {
    return t.tag === 5 || t.tag === 3 || t.tag === 27;
  }
  function Us(t) {
    return t && t.tag === 7 && t.stateNode !== null;
  }
  function ws(t) {
    var e = t.type, l = t.memoizedProps, a = t.stateNode;
    try {
      t: switch (e) {
        case "button":
        case "input":
        case "select":
        case "textarea":
          l.autoFocus && a.focus();
          break t;
        case "img":
          l.src ? a.src = l.src : l.srcSet && (a.srcset = l.srcSet);
      }
    } catch (n) {
      Et(t, t.return, n);
    }
  }
  function Hs(t, e, l) {
    try {
      var a = t.stateNode;
      tv(a, t.type, l, e), a[ye] = e;
    } catch (n) {
      Et(t, t.return, n);
    }
  }
  function Qd(t) {
    return t.tag === 5 || t.tag === 3 || t.tag === 26 || t.tag === 27 && Wl(t.type) || t.tag === 4;
  }
  function Bs(t) {
    t: for (; ; ) {
      for (; t.sibling === null; ) {
        if (t.return === null || Qd(t.return)) return null;
        t = t.return;
      }
      for (t.sibling.return = t.return, t = t.sibling; t.tag !== 5 && t.tag !== 6 && t.tag !== 18; ) {
        if (t.tag === 27 && Wl(t.type) || t.flags & 2 || t.child === null || t.tag === 4) continue t;
        t.child.return = t, t = t.child;
      }
      if (!(t.flags & 2)) return t.stateNode;
    }
  }
  function qs(t, e, l, a) {
    var n = t.tag;
    if (n === 5 || n === 6)
      n = t.stateNode, e ? (l.nodeType === 9 ? l.body : l.nodeName === "HTML" ? l.ownerDocument.body : l).insertBefore(n, e) : (e = l.nodeType === 9 ? l.body : l.nodeName === "HTML" ? l.ownerDocument.body : l, e.appendChild(n), l = l._reactRootContainer, l != null || e.onclick !== null || (e.onclick = tl)), Si(t, a), St = !0;
    else if (n !== 4 && (n === 27 && (Si(t, a), a = null, Wl(t.type) && (l = t.stateNode, e = null)), t = t.child, t !== null))
      for (qs(
        t,
        e,
        l,
        a
      ), t = t.sibling; t !== null; )
        qs(
          t,
          e,
          l,
          a
        ), t = t.sibling;
  }
  function _i(t, e, l, a) {
    var n = t.tag;
    if (n === 5 || n === 6)
      n = t.stateNode, e ? l.insertBefore(n, e) : l.appendChild(n), Si(t, a), St = !0;
    else if (n !== 4 && (n === 27 && (Si(t, a), a = null, Wl(t.type) && (l = t.stateNode)), t = t.child, t !== null))
      for (_i(
        t,
        e,
        l,
        a
      ), t = t.sibling; t !== null; )
        _i(
          t,
          e,
          l,
          a
        ), t = t.sibling;
  }
  function Vd(t) {
    var e = t.stateNode, l = t.memoizedProps;
    try {
      for (var a = t.type, n = e.attributes; n.length; )
        e.removeAttributeNode(n[0]);
      ce(e, a, l), e[le] = t, e[ye] = l;
    } catch (u) {
      Et(t, t.return, u);
    }
  }
  var Ni = !1, Ae = null;
  function Zd(t) {
    (t.tag === 30 || (t.subtreeFlags & 33554432) !== 0) && (Ni = !0);
  }
  var nl = null;
  function Kd() {
    var t = nl;
    return nl = null, t;
  }
  var ge = 0;
  function Ia(t, e, l, a, n) {
    return ge = 0, kd(
      t.child,
      e,
      l,
      a,
      n
    );
  }
  function kd(t, e, l, a, n) {
    for (var u = !1; t !== null; ) {
      if (t.tag === 5) {
        var i = t.stateNode;
        if (a !== null) {
          var f = _f(i);
          a.push(f), f.view && (u = !0);
        } else
          u || _f(i).view && (u = !0);
        Ni = !0, Km(
          i,
          ge === 0 ? e : e + "_" + ge,
          l
        ), ge++;
      } else (t.tag !== 22 || t.memoizedState === null) && (t.tag === 30 && n || kd(
        t.child,
        e,
        l,
        a,
        n
      ) && (u = !0));
      t = t.sibling;
    }
    return u;
  }
  function ul(t, e) {
    for (; t !== null; )
      t.tag === 5 ? km(t.stateNode, t.memoizedProps) : (t.tag !== 22 || t.memoizedState === null) && (t.tag === 30 && e || ul(
        t.child,
        e
      )), t = t.sibling;
  }
  function Ti(t) {
    if ((t.subtreeFlags & 18874368) !== 0)
      for (t = t.child; t !== null; ) {
        if ((t.tag !== 22 || t.memoizedState === null) && (Ti(t), t.tag === 30 && (t.flags & 18874368) !== 0 && t.stateNode.paired)) {
          var e = t.memoizedProps;
          if (e.name == null || e.name === "auto")
            throw Error(o(544));
          var l = e.name;
          e = gl(e.default, e.share), e !== "none" && (Ia(
            t,
            l,
            e,
            null,
            !1
          ) || ul(t.child, !1));
        }
        t = t.sibling;
      }
  }
  function Ys(t, e) {
    if (t.tag === 30) {
      var l = t.stateNode, a = t.memoizedProps, n = vl(a, l), u = gl(
        a.default,
        l.paired ? a.share : a.enter
      );
      u !== "none" ? Ia(t, n, u, null, !1) ? (Ti(t), l.paired || e || cn(t, a.onEnter)) : ul(t.child, !1) : Ti(t);
    } else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        Ys(t, e), t = t.sibling;
    else Ti(t);
  }
  function Ls(t) {
    if (Ae !== null && Ae.size !== 0) {
      var e = Ae;
      if ((t.subtreeFlags & 18874368) !== 0)
        for (t = t.child; t !== null; ) {
          if (t.tag !== 22 || t.memoizedState === null) {
            if (t.tag === 30 && (t.flags & 18874368) !== 0) {
              var l = t.memoizedProps, a = l.name;
              if (a != null && a !== "auto") {
                var n = e.get(a);
                if (n !== void 0) {
                  var u = gl(
                    l.default,
                    l.share
                  );
                  if (u !== "none" && (Ia(
                    t,
                    a,
                    u,
                    null,
                    !1
                  ) ? (u = t.stateNode, n.paired = u, u.paired = n, cn(t, l.onShare)) : ul(t.child, !1)), e.delete(a), e.size === 0) break;
                }
              }
            }
            Ls(t);
          }
          t = t.sibling;
        }
    }
  }
  function Xs(t) {
    if (t.tag === 30) {
      var e = t.memoizedProps, l = vl(e, t.stateNode), a = Ae !== null ? Ae.get(l) : void 0, n = gl(
        e.default,
        a !== void 0 ? e.share : e.exit
      );
      n !== "none" && (Ia(t, l, n, null, !1) ? a !== void 0 ? (n = t.stateNode, a.paired = n, n.paired = a, Ae.delete(l), cn(t, e.onShare)) : cn(t, e.onExit) : ul(t.child, !1)), Ae !== null && Ls(t);
    } else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        Xs(t), t = t.sibling;
    else
      Ae !== null && Ls(t);
  }
  function Jd(t) {
    for (t = t.child; t !== null; ) {
      if (t.tag === 30) {
        var e = t.memoizedProps, l = vl(e, t.stateNode);
        e = gl(e.default, e.update), t.flags &= -5, e !== "none" && Ia(
          t,
          l,
          e,
          t.memoizedState = [],
          !1
        );
      } else
        (t.subtreeFlags & 33554432) !== 0 && Jd(t);
      t = t.sibling;
    }
  }
  function Gs(t) {
    if ((t.subtreeFlags & 18874368) !== 0)
      for (t = t.child; t !== null; ) {
        if (t.tag !== 22 || t.memoizedState === null) {
          if (t.tag === 30 && (t.flags & 18874368) !== 0) {
            var e = t.stateNode;
            e.paired !== null && (e.paired = null, ul(t.child, !1));
          }
          Gs(t);
        }
        t = t.sibling;
      }
  }
  function Ei(t) {
    if (t.tag === 30)
      t.stateNode.paired = null, ul(t.child, !1), Gs(t);
    else if ((t.subtreeFlags & 33554432) !== 0)
      for (t = t.child; t !== null; )
        Ei(t), t = t.sibling;
    else Gs(t);
  }
  function $d(t) {
    for (t = t.child; t !== null; )
      t.tag === 30 ? ul(t.child, !1) : (t.subtreeFlags & 33554432) !== 0 && $d(t), t = t.sibling;
  }
  function Qs(t, e, l, a, n, u, i) {
    for (var f = !1; e !== null; ) {
      if (e.tag === 5) {
        var m = e.stateNode;
        if (u !== null && ge < u.length) {
          var x = u[ge], j = _f(m);
          (x.view || j.view) && (f = !0);
          var C;
          if (C = (t.flags & 4) === 0)
            if (j.clip) C = !0;
            else {
              C = x.rect;
              var g = j.rect;
              C = C.y !== g.y || C.x !== g.x || C.height !== g.height || C.width !== g.width;
            }
          C && (t.flags |= 4), j.abs ? j = !x.abs : (x = x.rect, j = j.rect, j = x.height !== j.height || x.width !== j.width), j && (t.flags |= 32);
        } else t.flags |= 32;
        (t.flags & 4) !== 0 && Km(
          m,
          ge === 0 ? l : l + "_" + ge,
          n
        ), f && (t.flags & 4) !== 0 || (nl === null && (nl = []), nl.push(
          m,
          ge === 0 ? a : a + "_" + ge,
          e.memoizedProps
        )), ge++;
      } else (e.tag !== 22 || e.memoizedState === null) && (e.tag === 30 && i ? t.flags |= e.flags & 32 : Qs(
        t,
        e.child,
        l,
        a,
        n,
        u,
        i
      ) && (f = !0));
      e = e.sibling;
    }
    return f;
  }
  function Fd(t, e) {
    for (t = t.child; t !== null; ) {
      if (t.tag === 30) {
        var l = t.memoizedProps, a = t.stateNode, n = vl(l, a), u = gl(l.default, l.update), i;
        i = t.memoizedState, t.memoizedState = null, a = t;
        var f = t.child;
        ge = 0, n = Qs(
          a,
          f,
          n,
          n,
          u,
          i,
          !1
        ), (t.flags & 4) !== 0 && n && cn(t, l.onUpdate);
      } else
        (t.subtreeFlags & 33554432) !== 0 && Fd(t);
      t = t.sibling;
    }
  }
  var Pt = !1, Nt = !1, il = !1, Vs = !1, Wd = typeof WeakSet == "function" ? WeakSet : Set, te = null, cl = !1, eu = !1, ji = !1, Zs = !1;
  function Oy(t, e, l) {
    if (t = t.containerInfo, gf = gn, t = er(t), Cc(t)) {
      if ("selectionStart" in t)
        var a = {
          start: t.selectionStart,
          end: t.selectionEnd
        };
      else
        t: {
          a = (a = t.ownerDocument) && a.defaultView || window;
          var n = a.getSelection && a.getSelection();
          if (n && n.rangeCount !== 0) {
            a = n.anchorNode;
            var u = n.anchorOffset, i = n.focusNode;
            n = n.focusOffset;
            try {
              a.nodeType, i.nodeType;
            } catch {
              a = null;
              break t;
            }
            var f = 0, m = -1, x = -1, j = 0, C = 0, g = t, T = null;
            e: for (; ; ) {
              for (var L; g !== a || u !== 0 && g.nodeType !== 3 || (m = f + u), g !== i || n !== 0 && g.nodeType !== 3 || (x = f + n), g.nodeType === 3 && (f += g.nodeValue.length), (L = g.firstChild) !== null; )
                T = g, g = L;
              for (; ; ) {
                if (g === t) break e;
                if (T === a && ++j === u && (m = f), T === i && ++C === n && (x = f), (L = g.nextSibling) !== null) break;
                g = T, T = g.parentNode;
              }
              g = L;
            }
            a = m === -1 || x === -1 ? null : { start: m, end: x };
          } else a = null;
        }
      a = a || { start: 0, end: 0 };
    } else a = null;
    for (pf = { focusedElem: t, selectionRange: a }, gn = !1, l = (l & 335544064) === l, te = e, e = l ? 9270 : 1024; te !== null; ) {
      if (t = te, l && (a = t.deletions, a !== null))
        for (u = 0; u < a.length; u++)
          l && Xs(a[u]);
      if (t.alternate === null && (t.flags & 2) !== 0)
        l && Zd(t), zi(l);
      else {
        if (t.tag === 22) {
          if (a = t.alternate, t.memoizedState !== null) {
            a !== null && a.memoizedState === null && l && Xs(a), zi(l);
            continue;
          } else if (a !== null && a.memoizedState !== null) {
            l && Zd(t), zi(l);
            continue;
          }
        }
        a = t.child, (t.subtreeFlags & e) !== 0 && a !== null ? (a.return = t, te = a) : (l && Jd(t), zi(l));
      }
    }
    Ae = null;
  }
  function zi(t) {
    for (; te !== null; ) {
      var e = te, l = t, a = e.alternate, n = e.flags;
      switch (e.tag) {
        case 0:
        case 11:
        case 15:
          break;
        case 1:
          if ((n & 1024) !== 0 && a !== null) {
            l = void 0, n = a.memoizedProps, a = a.memoizedState;
            var u = e.stateNode;
            try {
              var i = Sa(
                e.type,
                n
              );
              l = u.getSnapshotBeforeUpdate(
                i,
                a
              ), u.__reactInternalSnapshotBeforeUpdate = l;
            } catch (f) {
              Et(e, e.return, f);
            }
          }
          break;
        case 3:
          if ((n & 1024) !== 0) {
            if (a = e.stateNode.containerInfo, l = a.nodeType, l === 9)
              Ef(a);
            else if (l === 1)
              switch (a.nodeName) {
                case "HEAD":
                case "HTML":
                case "BODY":
                  Ef(a);
                  break;
                default:
                  a.textContent = "";
              }
          }
          break;
        case 5:
        case 26:
        case 27:
        case 6:
        case 4:
        case 17:
          break;
        case 30:
          l && a !== null && (l = vl(
            a.memoizedProps,
            a.stateNode
          ), n = e.memoizedProps, n = gl(n.default, n.update), n !== "none" && Ia(
            a,
            l,
            n,
            a.memoizedState = [],
            !0
          ));
          break;
        default:
          if ((n & 1024) !== 0) throw Error(o(163));
      }
      if (a = e.sibling, a !== null) {
        a.return = e.return, te = a;
        break;
      }
      te = e.return;
    }
  }
  function Id(t, e, l) {
    var a = l.flags;
    switch (l.tag) {
      case 0:
      case 11:
      case 15:
        sl(t, l), a & 4 && Pn(5, l);
        break;
      case 1:
        if (sl(t, l), a & 4)
          if (t = l.stateNode, e === null)
            try {
              t.componentDidMount();
            } catch (i) {
              Et(l, l.return, i);
            }
          else {
            var n = Sa(
              l.type,
              e.memoizedProps
            );
            e = e.memoizedState;
            try {
              t.componentDidUpdate(
                n,
                e,
                t.__reactInternalSnapshotBeforeUpdate
              );
            } catch (i) {
              Et(
                l,
                l.return,
                i
              );
            }
          }
        a & 64 && Ld(l), a & 512 && al(l, l.return);
        break;
      case 3:
        if (sl(t, l), a & 64 && (t = l.updateQueue, t !== null)) {
          if (e = null, l.child !== null)
            switch (l.child.tag) {
              case 27:
              case 5:
                e = l.child.stateNode;
                break;
              case 1:
                e = l.child.stateNode;
            }
          try {
            Or(t, e);
          } catch (i) {
            Et(l, l.return, i);
          }
        }
        break;
      case 27:
        e === null && a & 4 && Vd(l);
      case 26:
      case 5:
        sl(t, l), e === null && a & 4 && ws(l), a & 512 && al(l, l.return);
        break;
      case 12:
        sl(t, l);
        break;
      case 31:
        sl(t, l), a & 4 && lm(t, l);
        break;
      case 13:
        sl(t, l), a & 4 && am(t, l), a & 64 && (t = l.memoizedState, t !== null && (t = t.dehydrated, t !== null && (l = Xy.bind(
          null,
          l
        ), _v(t, l))));
        break;
      case 22:
        if (a = l.memoizedState !== null || Pt, !a) {
          var u = e !== null && e.memoizedState !== null || Nt;
          e = Pt, n = Nt, Pt = a, (Nt = u) && !n ? (a = 2, (l.subtreeFlags & 8772) !== 0 && (a |= 1), Fe(
            t,
            l,
            a
          )) : sl(t, l), Pt = e, Nt = n;
        }
        break;
      case 30:
        sl(t, l), a & 512 && al(l, l.return);
        break;
      case 7:
        a & 512 && al(l, l.return);
      default:
        sl(t, l);
    }
  }
  function Ks(t, e) {
    for (t = t.child; t !== null; )
      Pd(t, e), t = t.sibling;
  }
  function Pd(t, e) {
    switch (t.tag) {
      case 5:
      case 26:
        try {
          var l = t.stateNode;
          if (e) {
            var a = l.style;
            typeof a.setProperty == "function" ? a.setProperty("display", "none", "important") : a.display = "none";
          } else {
            var n = t.stateNode, u = t.memoizedProps.style, i = u != null && u.hasOwnProperty("display") ? u.display : null;
            n.style.display = i == null || typeof i == "boolean" ? "" : ("" + i).trim();
          }
        } catch (m) {
          Et(t, t.return, m);
        }
        ks(t, e);
        break;
      case 6:
        try {
          t.stateNode.nodeValue = e ? "" : t.memoizedProps, St = !0;
        } catch (m) {
          Et(t, t.return, m);
        }
        break;
      case 18:
        try {
          var f = t.stateNode;
          e ? Zm(f, !0) : Zm(t.stateNode, !1);
        } catch (m) {
          Et(t, t.return, m);
        }
        break;
      case 22:
      case 23:
        t.memoizedState === null && Ks(t, e);
        break;
      default:
        Ks(t, e);
    }
  }
  function ks(t, e) {
    if (t.subtreeFlags & 67108864)
      for (t = t.child; t !== null; ) {
        t: {
          var l = t, a = e;
          switch (l.tag) {
            case 4:
              Pd(l, a);
              break t;
            case 22:
              l.memoizedState === null && ks(l, a);
              break t;
            default:
              ks(l, a);
          }
        }
        t = t.sibling;
      }
  }
  function tm(t) {
    var e = t.alternate;
    e !== null && (t.alternate = null, tm(e)), t.child = null, t.deletions = null, t.sibling = null, t.tag === 5 && (e = t.stateNode, e !== null && Ru(e)), t.stateNode = null, t.return = null, t.dependencies = null, t.memoizedProps = null, t.memoizedState = null, t.pendingProps = null, t.stateNode = null, t.updateQueue = null;
  }
  var Ut = null, pe = !1;
  function Je(t, e, l) {
    for (l = l.child; l !== null; )
      em(t, e, l), l = l.sibling;
  }
  function em(t, e, l) {
    if (Ne && typeof Ne.onCommitFiberUnmount == "function")
      try {
        Ne.onCommitFiberUnmount(Tn, l);
      } catch {
      }
    switch (l.tag) {
      case 26:
        Nt || ie(l, e), Je(
          t,
          e,
          l
        ), l.memoizedState ? l.memoizedState.count-- : l.stateNode && !Nt && (l = l.stateNode, l.parentNode.removeChild(l));
        break;
      case 27:
        Nt || ie(l, e), tu(l);
        var a = Ut, n = pe;
        Wl(l.type) && (Ut = l.stateNode, pe = !1), Je(
          t,
          e,
          l
        ), uh(
          l.stateNode,
          l.type,
          l.memoizedProps
        ), Ut = a, pe = n;
        break;
      case 5:
        Nt || ie(l, e), tu(l);
      case 6:
        if (l.tag === 6 && tu(l), a = Ut, n = pe, Ut = null, Je(
          t,
          e,
          l
        ), Ut = a, pe = n, Ut !== null)
          if (pe)
            try {
              (Ut.nodeType === 9 ? Ut.body : Ut.nodeName === "HTML" ? Ut.ownerDocument.body : Ut).removeChild(l.stateNode), St = !0;
            } catch (u) {
              Et(
                l,
                e,
                u
              );
            }
          else
            try {
              Ut.removeChild(l.stateNode), St = !0;
            } catch (u) {
              Et(
                l,
                e,
                u
              );
            }
        break;
      case 18:
        Ut !== null && (pe ? (t = Ut, Vm(
          t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t,
          l.stateNode
        ), pn(t)) : Vm(Ut, l.stateNode));
        break;
      case 4:
        a = Ut, n = pe, Ut = l.stateNode.containerInfo, pe = !0, Je(
          t,
          e,
          l
        ), Ut = a, pe = n;
        break;
      case 0:
      case 11:
      case 14:
      case 15:
        Vl(2, l, e), Nt || Vl(4, l, e), Je(
          t,
          e,
          l
        );
        break;
      case 1:
        Nt || (ie(l, e), a = l.stateNode, typeof a.componentWillUnmount == "function" && Xd(
          l,
          e,
          a
        )), Je(
          t,
          e,
          l
        );
        break;
      case 21:
        Je(
          t,
          e,
          l
        );
        break;
      case 22:
        Nt = (a = Nt) || l.memoizedState !== null, Je(
          t,
          e,
          l
        ), Nt = a;
        break;
      case 30:
        ie(l, e), Je(
          t,
          e,
          l
        );
        break;
      case 7:
        Nt || ie(l, e), Je(
          t,
          e,
          l
        );
        break;
      default:
        Je(
          t,
          e,
          l
        );
    }
  }
  function lm(t, e) {
    if (e.memoizedState === null && (t = e.alternate, t !== null && (t = t.memoizedState, t !== null))) {
      t = t.dehydrated;
      try {
        pn(t);
      } catch (l) {
        Et(e, e.return, l);
      }
    }
  }
  function am(t, e) {
    if (e.memoizedState === null && (t = e.alternate, t !== null && (t = t.memoizedState, t !== null && (t = t.dehydrated, t !== null))))
      try {
        pn(t);
      } catch (l) {
        Et(e, e.return, l);
      }
  }
  function My(t) {
    switch (t.tag) {
      case 31:
      case 13:
      case 19:
        var e = t.stateNode;
        return e === null && (e = t.stateNode = new Wd()), e;
      case 22:
        return t = t.stateNode, e = t._retryCache, e === null && (e = t._retryCache = new Wd()), e;
      default:
        throw Error(o(435, t.tag));
    }
  }
  function Ai(t, e) {
    var l = My(t);
    e.forEach(function(a) {
      if (!l.has(a)) {
        l.add(a);
        var n = Gy.bind(null, t, a);
        a.then(n, n);
      }
    });
  }
  function de(t, e, l) {
    var a = e.deletions;
    if (a !== null)
      for (var n = 0; n < a.length; n++) {
        var u = a[n], i = t, f = e, m = f;
        t: for (; m !== null; ) {
          switch (m.tag) {
            case 27:
              if (Wl(m.type)) {
                Ut = m.stateNode, pe = !1;
                break t;
              }
              break;
            case 5:
              Ut = m.stateNode, pe = !1;
              break t;
            case 3:
            case 4:
              Ut = m.stateNode.containerInfo, pe = !0;
              break t;
          }
          m = m.return;
        }
        if (Ut === null) throw Error(o(160));
        em(i, f, u), Ut = null, pe = !1, i = u.alternate, i !== null && (i.return = null), u.return = null;
      }
    if (e.subtreeFlags & 13886)
      for (e = e.child; e !== null; )
        nm(e, t, l), e = e.sibling;
  }
  var $e = null;
  function nm(t, e, l) {
    var a = t.alternate, n = t.flags;
    switch (t.tag) {
      case 0:
      case 11:
      case 14:
      case 15:
        if (n & 4 && (a = t.updateQueue, a = a !== null ? a.events : null, a !== null))
          for (var u = 0; u < a.length; u++) {
            var i = a[u];
            i.ref.impl = i.nextImpl;
          }
        de(e, t, l), me(t), n & 4 && (Vl(3, t, t.return), Pn(3, t), Vl(5, t, t.return));
        break;
      case 1:
        de(e, t, l), me(t), n & 512 && (Nt || a === null || ie(a, a.return)), n & 64 && Pt && (t = t.updateQueue, t !== null && (e = t.callbacks, e !== null && (l = t.shared.hiddenCallbacks, t.shared.hiddenCallbacks = l === null ? e : l.concat(e))));
        break;
      case 26:
        if (u = $e, de(e, t, l), me(t), n & 512 && (Nt || a === null || ie(a, a.return)), n & 4)
          if (n = a !== null ? a.memoizedState : null, l = t.memoizedState, a === null)
            if (l === null)
              if (t.stateNode === null)
                if (Pt)
                  t.stateNode = Xm(
                    t.type,
                    t.memoizedProps,
                    e.containerInfo,
                    t
                  );
                else {
                  t: {
                    e = t.type, l = t.memoizedProps, n = u.ownerDocument || u;
                    e: switch (e) {
                      case "title":
                        a = n.getElementsByTagName("title")[0], (!a || a[zn] || a[le] || a.namespaceURI === "http://www.w3.org/2000/svg" || a.hasAttribute("itemprop")) && (a = n.createElement(e), n.head.insertBefore(
                          a,
                          n.querySelector("head > title")
                        )), ce(a, e, l), a[le] = t, Wt(a), e = a;
                        break t;
                      case "link":
                        if (u = rh(
                          "link",
                          "href",
                          n
                        ).get(e + (l.href || ""))) {
                          for (i = 0; i < u.length; i++)
                            if (a = u[i], a.getAttribute("href") === (l.href == null || l.href === "" ? null : l.href) && a.getAttribute("rel") === (l.rel == null ? null : l.rel) && a.getAttribute("title") === (l.title == null ? null : l.title) && a.getAttribute("crossorigin") === (l.crossOrigin == null ? null : l.crossOrigin)) {
                              u.splice(i, 1);
                              break e;
                            }
                        }
                        a = n.createElement(e), ce(a, e, l), n.head.appendChild(a);
                        break;
                      case "meta":
                        if (u = rh(
                          "meta",
                          "content",
                          n
                        ).get(e + (l.content || ""))) {
                          for (i = 0; i < u.length; i++)
                            if (a = u[i], a.getAttribute("content") === (l.content == null ? null : "" + l.content) && a.getAttribute("name") === (l.name == null ? null : l.name) && a.getAttribute("property") === (l.property == null ? null : l.property) && a.getAttribute("http-equiv") === (l.httpEquiv == null ? null : l.httpEquiv) && a.getAttribute("charset") === (l.charSet == null ? null : l.charSet)) {
                              u.splice(i, 1);
                              break e;
                            }
                        }
                        a = n.createElement(e), ce(a, e, l), n.head.appendChild(a);
                        break;
                      default:
                        throw Error(o(468, e));
                    }
                    a[le] = t, Wt(a), e = a;
                  }
                  t.stateNode = e;
                }
              else
                Pt || Rf(u, t.type, t.stateNode);
            else
              t.stateNode = oh(
                u,
                l,
                t.memoizedProps
              );
          else
            n !== l ? (n === null ? (e = a.stateNode, e === null || Nt || e.parentNode.removeChild(e)) : n.count--, l === null ? Pt || Rf(u, t.type, t.stateNode) : oh(u, l, t.memoizedProps)) : l === null && t.stateNode !== null && Hs(
              t,
              t.memoizedProps,
              a.memoizedProps
            );
        break;
      case 27:
        de(e, t, l), me(t), n & 512 && (Nt || a === null || ie(a, a.return)), a !== null && n & 4 && Hs(
          t,
          t.memoizedProps,
          a.memoizedProps
        );
        break;
      case 5:
        if (u = il, il = !1, de(e, t, l), il = u, me(t), n & 512 && (Nt || a === null || ie(a, a.return)), t.flags & 32) {
          e = t.stateNode;
          try {
            Ua(e, ""), St = !0;
          } catch (j) {
            Et(t, t.return, j);
          }
        }
        n & 4 && t.stateNode != null && (e = t.memoizedProps, Hs(
          t,
          e,
          a !== null ? a.memoizedProps : e
        )), n & 1024 && (Vs = !0);
        break;
      case 6:
        if (de(e, t, l), me(t), n & 4) {
          if (t.stateNode === null)
            throw Error(o(162));
          e = t.memoizedProps, l = t.stateNode;
          try {
            l.nodeValue = e, St = !0;
          } catch (j) {
            Et(t, t.return, j);
          }
        }
        break;
      case 3:
        if (St = !1, Qi = null, u = $e, $e = ou(e.containerInfo), de(e, t, l), $e = u, me(t), n & 4 && a !== null && a.memoizedState.isDehydrated)
          try {
            pn(e.containerInfo);
          } catch (j) {
            Et(t, t.return, j);
          }
        Vs && (Vs = !1, um(t)), St = !1;
        break;
      case 4:
        n = il, il = Pt, a = Eo(), u = $e, $e = ou(
          t.stateNode.containerInfo
        ), de(e, t, l), me(t), $e = u, St && eu && (ji = !0), St = a, il = n;
        break;
      case 12:
        de(e, t, l), me(t);
        break;
      case 31:
        de(e, t, l), me(t), n & 4 && (e = t.updateQueue, e !== null && (t.updateQueue = null, Ai(t, e)));
        break;
      case 13:
        de(e, t, l), me(t), t.child.flags & 8192 && t.memoizedState !== null != (a !== null && a.memoizedState !== null) && (Ci = _e()), n & 4 && (e = t.updateQueue, e !== null && (t.updateQueue = null, Ai(t, e)));
        break;
      case 22:
        u = t.memoizedState !== null, i = a !== null && a.memoizedState !== null;
        var f = Pt, m = Nt, x = il;
        Pt = f || u, il = x || u, Nt = m || i, de(e, t, l), Nt = m, il = x, Pt = f, me(t), n & 8192 && (e = t.stateNode, e._visibility = u ? e._visibility & -2 : e._visibility | 1, !u || a === null || i || Pt || Nt || (e = i || Nt, l = Pt, a = Nt, Pt = u || Pt, Nt = e, Zl(t, 2), Pt = l, Nt = a), !u && il || Ks(t, u)), n & 4 && (e = t.updateQueue, e !== null && (l = e.retryQueue, l !== null && (e.retryQueue = null, Ai(t, l))));
        break;
      case 19:
        de(e, t, l), me(t), n & 4 && (e = t.updateQueue, e !== null && (t.updateQueue = null, Ai(t, e)));
        break;
      case 30:
        n & 512 && (Nt || a === null || ie(a, a.return)), n = Eo(), u = eu, i = (l & 335544064) === l, f = t.memoizedProps, eu = i && gl(
          f.default,
          f.update
        ) !== "none", de(e, t, l), me(t), i && a !== null && St && (t.flags |= 4), eu = u, St = n;
        break;
      case 21:
        break;
      case 7:
        n & 512 && (Nt || a === null || ie(a, a.return)), a && a.stateNode !== null && (a.stateNode._fragmentFiber = t);
      default:
        de(e, t, l), me(t);
    }
  }
  function me(t) {
    var e = t.flags;
    if (e & 2) {
      try {
        for (var l, a = t.return; a !== null; ) {
          if (Qd(a)) {
            l = a;
            break;
          }
          a = a.return;
        }
        a = null;
        for (var n = t.return; n !== null; ) {
          if (Us(n)) {
            var u = n.stateNode;
            a === null ? a = [u] : a.push(u);
          }
          if (Ds(n)) break;
          n = n.return;
        }
        var i = a;
        if (l == null) throw Error(o(160));
        switch (l.tag) {
          case 27:
            var f = l.stateNode, m = Bs(t);
            _i(
              t,
              m,
              f,
              i
            );
            break;
          case 5:
            var x = l.stateNode;
            l.flags & 32 && (Ua(x, ""), l.flags &= -33);
            var j = Bs(t);
            _i(
              t,
              j,
              x,
              i
            );
            break;
          case 3:
          case 4:
            var C = l.stateNode.containerInfo, g = Bs(t);
            qs(
              t,
              g,
              C,
              i
            );
            break;
          default:
            throw Error(o(161));
        }
      } catch (T) {
        Et(t, t.return, T);
      }
      t.flags &= -3;
    }
    e & 4096 && (t.flags &= -4097);
  }
  function um(t) {
    if (t.subtreeFlags & 1024)
      for (t = t.child; t !== null; ) {
        var e = t;
        um(e), e.tag === 5 && e.flags & 1024 && (e = e.stateNode, gn = !0, e.reset(), gn = !1), t = t.sibling;
      }
  }
  function Pa(t, e) {
    if (e.subtreeFlags & 9270)
      for (e = e.child; e !== null; )
        im(e, t), e = e.sibling;
    else Fd(e);
  }
  function im(t, e) {
    var l = t.alternate;
    if (l === null) Ys(t, !1);
    else
      switch (t.tag) {
        case 3:
          if (Zs = cl = !1, Kd(), Pa(e, t), !cl && !ji) {
            if (t = nl, t !== null)
              for (var a = 0; a < t.length; a += 3) {
                l = t[a];
                var n = t[a + 1];
                km(l, t[a + 2]), l = l.ownerDocument.documentElement, l !== null && l.animate(
                  { opacity: [0, 0], pointerEvents: ["none", "none"] },
                  {
                    duration: 0,
                    fill: "forwards",
                    pseudoElement: "::view-transition-group(" + n + ")"
                  }
                );
              }
            t = e.containerInfo, t = t.nodeType === 9 ? t.documentElement : t.ownerDocument.documentElement, t !== null && t.style.viewTransitionName === "" && (t.style.viewTransitionName = "none", t.animate(
              { opacity: [0, 0], pointerEvents: ["none", "none"] },
              {
                duration: 0,
                fill: "forwards",
                pseudoElement: "::view-transition-group(root)"
              }
            ), t.animate(
              { width: [0, 0], height: [0, 0] },
              {
                duration: 0,
                fill: "forwards",
                pseudoElement: "::view-transition"
              }
            )), Zs = !0;
          }
          nl = null;
          break;
        case 5:
          Pa(e, t);
          break;
        case 4:
          a = cl, cl = !1, Pa(e, t), cl && (ji = !0), cl = a;
          break;
        case 22:
          t.memoizedState === null && (l.memoizedState !== null ? Ys(t, !1) : Pa(e, t));
          break;
        case 30:
          a = cl, n = Kd(), cl = !1, Pa(e, t), cl && (t.flags |= 4);
          var u = t.memoizedProps, i = t.stateNode;
          e = vl(u, i), i = vl(l.memoizedProps, i);
          var f = gl(u.default, u.update);
          f === "none" ? e = !1 : (u = l.memoizedState, l.memoizedState = null, l = t.child, ge = 0, e = Qs(
            t,
            l,
            e,
            i,
            f,
            u,
            !0
          ), ge !== (u === null ? 0 : u.length) && (t.flags |= 32)), (t.flags & 4) !== 0 && e ? (cn(
            t,
            t.memoizedProps.onUpdate
          ), nl = n) : n !== null && (n.push.apply(n, nl), nl = n), cl = (t.flags & 32) !== 0 ? !0 : a;
          break;
        default:
          Pa(e, t);
      }
  }
  function sl(t, e) {
    if (e.subtreeFlags & 8772)
      for (e = e.child; e !== null; )
        Id(t, e.alternate, e), e = e.sibling;
  }
  function Zl(t, e) {
    for (t = t.child; t !== null; ) {
      var l = t, a = e;
      switch (l.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          Vl(4, l, l.return), Zl(
            l,
            a
          );
          break;
        case 1:
          ie(l, l.return);
          var n = l.stateNode;
          typeof n.componentWillUnmount == "function" && Xd(
            l,
            l.return,
            n
          ), Zl(
            l,
            a
          );
          break;
        case 27:
          (a & 2) !== 0 && uh(
            l.stateNode,
            l.type,
            l.memoizedProps
          );
        case 5:
          ie(l, l.return), l.tag !== 5 && l.tag !== 27 || tu(l), Zl(
            l,
            a
          );
          break;
        case 6:
          tu(l);
          break;
        case 26:
          ie(l, l.return), n = l.stateNode, l.memoizedState !== null || n === null || Nt || n.parentNode.removeChild(n), Zl(
            l,
            a
          );
          break;
        case 22:
          l.memoizedState === null && Zl(
            l,
            a
          );
          break;
        case 30:
          ie(l, l.return), Zl(
            l,
            a
          );
          break;
        case 7:
          ie(l, l.return);
        default:
          Zl(
            l,
            a
          );
      }
      t = t.sibling;
    }
  }
  function Fe(t, e, l) {
    for (l = (e.subtreeFlags & 8772) !== 0 ? l : l & -2, e = e.child; e !== null; ) {
      var a = e.alternate, n = t, u = e, i = u.flags, f = (l & 1) !== 0;
      switch (u.tag) {
        case 0:
        case 11:
        case 15:
          Fe(
            n,
            u,
            l
          ), Pn(4, u);
          break;
        case 1:
          if (Fe(
            n,
            u,
            l
          ), a = u, n = a.stateNode, typeof n.componentDidMount == "function")
            try {
              n.componentDidMount();
            } catch (j) {
              Et(a, a.return, j);
            }
          if (a = u, n = a.updateQueue, n !== null) {
            var m = a.stateNode;
            try {
              var x = n.shared.hiddenCallbacks;
              if (x !== null)
                for (n.shared.hiddenCallbacks = null, n = 0; n < x.length; n++)
                  Ar(x[n], m);
            } catch (j) {
              Et(a, a.return, j);
            }
          }
          f && i & 64 && Ld(u), al(u, u.return);
          break;
        case 27:
          (l & 2) !== 0 && Vd(u);
        case 5:
          u.tag !== 5 && u.tag !== 27 || Gd(u), Fe(
            n,
            u,
            l
          ), f && a === null && i & 4 && ws(u), al(u, u.return);
          break;
        case 6:
          Gd(u);
          break;
        case 26:
          m = u.stateNode, u.memoizedState !== null || m === null || Pt || Rf(
            ou(m.ownerDocument),
            u.type,
            m
          ), Fe(
            n,
            u,
            l
          ), f && a === null && i & 4 && ws(u), al(u, u.return);
          break;
        case 12:
          Fe(
            n,
            u,
            l
          );
          break;
        case 31:
          Fe(
            n,
            u,
            l
          ), f && i & 4 && lm(n, u);
          break;
        case 13:
          Fe(
            n,
            u,
            l
          ), f && i & 4 && am(n, u);
          break;
        case 22:
          u.memoizedState === null && Fe(
            n,
            u,
            l
          ), al(u, u.return);
          break;
        case 30:
          Fe(
            n,
            u,
            l
          ), al(u, u.return);
          break;
        case 7:
          al(u, u.return);
        default:
          Fe(
            n,
            u,
            l
          );
      }
      e = e.sibling;
    }
  }
  function Js(t, e) {
    var l = null;
    t !== null && t.memoizedState !== null && t.memoizedState.cachePool !== null && (l = t.memoizedState.cachePool.pool), t = null, e.memoizedState !== null && e.memoizedState.cachePool !== null && (t = e.memoizedState.cachePool.pool), t !== l && (t != null && t.refCount++, l != null && Ln(l));
  }
  function $s(t, e) {
    t = null, e.alternate !== null && (t = e.alternate.memoizedState.cache), e = e.memoizedState.cache, e !== t && (e.refCount++, t != null && Ln(t));
  }
  function Ge(t, e, l, a) {
    var n = (l & 335544064) === l;
    if (e.subtreeFlags & (n ? 10262 : 10256))
      for (e = e.child; e !== null; )
        cm(
          t,
          e,
          l,
          a
        ), e = e.sibling;
    else n && $d(e);
  }
  function cm(t, e, l, a) {
    var n = (l & 335544064) === l;
    n && e.alternate === null && e.return !== null && e.return.alternate !== null && Ei(e);
    var u = e.flags;
    switch (e.tag) {
      case 0:
      case 11:
      case 15:
        Ge(
          t,
          e,
          l,
          a
        ), u & 2048 && Pn(9, e);
        break;
      case 1:
        Ge(
          t,
          e,
          l,
          a
        );
        break;
      case 3:
        Ge(
          t,
          e,
          l,
          a
        ), n && Zs && (t = t.containerInfo, t = t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t, t.style.viewTransitionName === "root" && (t.style.viewTransitionName = ""), t = t.ownerDocument.documentElement, t !== null && t.style.viewTransitionName === "none" && (t.style.viewTransitionName = "")), u & 2048 && (u = null, e.alternate !== null && (u = e.alternate.memoizedState.cache), e = e.memoizedState.cache, e !== u && (e.refCount++, u != null && Ln(u)));
        break;
      case 12:
        if (u & 2048) {
          Ge(
            t,
            e,
            l,
            a
          ), u = e.stateNode;
          try {
            var i = e.memoizedProps, f = i.id, m = i.onPostCommit;
            typeof m == "function" && m(
              f,
              e.alternate === null ? "mount" : "update",
              u.passiveEffectDuration,
              -0
            );
          } catch (x) {
            Et(e, e.return, x);
          }
        } else
          Ge(
            t,
            e,
            l,
            a
          );
        break;
      case 31:
        Ge(
          t,
          e,
          l,
          a
        );
        break;
      case 13:
        Ge(
          t,
          e,
          l,
          a
        );
        break;
      case 23:
        break;
      case 22:
        i = e.stateNode, f = e.alternate, e.memoizedState !== null ? (n && f !== null && f.memoizedState === null && Ei(f), i._visibility & 2 ? Ge(
          t,
          e,
          l,
          a
        ) : lu(
          t,
          e
        )) : (n && f !== null && f.memoizedState !== null && Ei(e), i._visibility & 2 ? Ge(
          t,
          e,
          l,
          a
        ) : (i._visibility |= 2, tn(
          t,
          e,
          l,
          a,
          (e.subtreeFlags & 10256) !== 0 || !1
        ))), u & 2048 && Js(f, e);
        break;
      case 24:
        Ge(
          t,
          e,
          l,
          a
        ), u & 2048 && $s(e.alternate, e);
        break;
      case 30:
        n && (u = e.alternate, u !== null && (ul(u.child, !0), ul(e.child, !0))), Ge(
          t,
          e,
          l,
          a
        );
        break;
      default:
        Ge(
          t,
          e,
          l,
          a
        );
    }
  }
  function tn(t, e, l, a, n) {
    for (n = n && ((e.subtreeFlags & 10256) !== 0 || !1), e = e.child; e !== null; ) {
      var u = t, i = e, f = l, m = a, x = i.flags;
      switch (i.tag) {
        case 0:
        case 11:
        case 15:
          tn(
            u,
            i,
            f,
            m,
            n
          ), Pn(8, i);
          break;
        case 23:
          break;
        case 22:
          var j = i.stateNode;
          i.memoizedState !== null ? j._visibility & 2 ? tn(
            u,
            i,
            f,
            m,
            n
          ) : lu(
            u,
            i
          ) : (j._visibility |= 2, tn(
            u,
            i,
            f,
            m,
            n
          )), n && x & 2048 && Js(
            i.alternate,
            i
          );
          break;
        case 24:
          tn(
            u,
            i,
            f,
            m,
            n
          ), n && x & 2048 && $s(i.alternate, i);
          break;
        default:
          tn(
            u,
            i,
            f,
            m,
            n
          );
      }
      e = e.sibling;
    }
  }
  function lu(t, e) {
    if (e.subtreeFlags & 10256)
      for (e = e.child; e !== null; ) {
        var l = t, a = e, n = a.flags;
        switch (a.tag) {
          case 22:
            lu(l, a), n & 2048 && Js(
              a.alternate,
              a
            );
            break;
          case 24:
            lu(l, a), n & 2048 && $s(a.alternate, a);
            break;
          default:
            lu(l, a);
        }
        e = e.sibling;
      }
  }
  var _a = 8192;
  function Na(t, e, l) {
    if (t.subtreeFlags & _a)
      for (t = t.child; t !== null; )
        sm(
          t,
          e,
          l
        ), t = t.sibling;
  }
  function sm(t, e, l) {
    switch (t.tag) {
      case 26:
        Na(
          t,
          e,
          l
        ), t.flags & _a && (t.memoizedState !== null ? Hv(
          l,
          $e,
          t.memoizedState,
          t.memoizedProps
        ) : (t = t.stateNode, (e & 335544128) === e && yh(l, t)));
        break;
      case 5:
        Na(
          t,
          e,
          l
        ), t.flags & _a && (t = t.stateNode, (e & 335544128) === e && yh(l, t));
        break;
      case 3:
      case 4:
        var a = $e;
        $e = ou(t.stateNode.containerInfo), Na(
          t,
          e,
          l
        ), $e = a;
        break;
      case 22:
        t.memoizedState === null && (a = t.alternate, a !== null && a.memoizedState !== null ? (a = _a, _a = 16777216, Na(
          t,
          e,
          l
        ), _a = a) : Na(
          t,
          e,
          l
        ));
        break;
      case 30:
        if ((t.flags & _a) !== 0 && (a = t.memoizedProps.name, a != null && a !== "auto")) {
          var n = t.stateNode;
          n.paired = null, Ae === null && (Ae = /* @__PURE__ */ new Map()), Ae.set(a, n);
        }
        Na(
          t,
          e,
          l
        );
        break;
      default:
        Na(
          t,
          e,
          l
        );
    }
  }
  function fm(t) {
    var e = t.alternate;
    if (e !== null && (t = e.child, t !== null)) {
      e.child = null;
      do
        e = t.sibling, t.sibling = null, t = e;
      while (t !== null);
    }
  }
  function au(t) {
    var e = t.deletions;
    if ((t.flags & 16) !== 0) {
      if (e !== null)
        for (var l = 0; l < e.length; l++) {
          var a = e[l];
          te = a, rm(
            a,
            t
          );
        }
      fm(t);
    }
    if (t.subtreeFlags & 10256)
      for (t = t.child; t !== null; )
        om(t), t = t.sibling;
  }
  function om(t) {
    switch (t.tag) {
      case 0:
      case 11:
      case 15:
        au(t), t.flags & 2048 && Vl(9, t, t.return);
        break;
      case 3:
        au(t);
        break;
      case 12:
        au(t);
        break;
      case 22:
        var e = t.stateNode;
        t.memoizedState !== null && e._visibility & 2 && (t.return === null || t.return.tag !== 13) ? (e._visibility &= -3, Oi(t)) : au(t);
        break;
      default:
        au(t);
    }
  }
  function Oi(t) {
    var e = t.deletions;
    if ((t.flags & 16) !== 0) {
      if (e !== null)
        for (var l = 0; l < e.length; l++) {
          var a = e[l];
          te = a, rm(
            a,
            t
          );
        }
      fm(t);
    }
    for (t = t.child; t !== null; ) {
      switch (e = t, e.tag) {
        case 0:
        case 11:
        case 15:
          Vl(8, e, e.return), Oi(e);
          break;
        case 22:
          l = e.stateNode, l._visibility & 2 && (l._visibility &= -3, Oi(e));
          break;
        default:
          Oi(e);
      }
      t = t.sibling;
    }
  }
  function rm(t, e) {
    for (; te !== null; ) {
      var l = te;
      switch (l.tag) {
        case 0:
        case 11:
        case 15:
          Vl(8, l, e);
          break;
        case 23:
        case 22:
          if (l.memoizedState !== null && l.memoizedState.cachePool !== null) {
            var a = l.memoizedState.cachePool.pool;
            a != null && a.refCount++;
          }
          break;
        case 24:
          Ln(l.memoizedState.cache);
      }
      if (a = l.child, a !== null) a.return = l, te = a;
      else
        t: for (l = t; te !== null; ) {
          a = te;
          var n = a.sibling, u = a.return;
          if (tm(a), a === l) {
            te = null;
            break t;
          }
          if (n !== null) {
            n.return = u, te = n;
            break t;
          }
          te = u;
        }
    }
  }
  var Cy = {
    getCacheForType: function(t) {
      var e = ae(Zt), l = e.data.get(t);
      return l === void 0 && (l = t(), e.data.set(t, l)), l;
    },
    cacheSignal: function() {
      return ae(Zt).controller.signal;
    }
  }, Ry = typeof WeakMap == "function" ? WeakMap : Map, _t = 0, At = null, mt = null, yt = 0, Tt = 0, Oe = null, Kl = !1, en = !1, Fs = !1, jl = 0, Gt = 0, kl = 0, Ta = 0, Mi = 0, Me = 0, ln = 0, nu = null, be = null, Ws = !1, Ci = 0, dm = 0, Ri = 1 / 0, Di = null, Jl = null, Bt = 0, We = null, Ea = null, fl = 0, Is = 0, Ps = null, mm = null, an = null, nn = null, un = null, uu = 0, Ui = null;
  function Ce() {
    return (_t & 2) !== 0 && yt !== 0 ? yt & -yt : G.T !== null ? of() : vo();
  }
  function hm() {
    if (Me === 0)
      if ((yt & 536870912) === 0 || ot) {
        var t = Au;
        Au <<= 1, (Au & 3932160) === 0 && (Au = 262144), Me = t;
      } else Me = 536870912;
    return t = ne.current, t !== null && (t.flags |= 32), Me;
  }
  function cn(t, e) {
    if (e != null) {
      var l = t.stateNode, a = l.ref;
      a === null && (a = l.ref = Jm(
        vl(t.memoizedProps, l)
      )), nn === null && (nn = []), nn.push(e.bind(null, a));
    }
  }
  function xe(t, e, l) {
    (t === At && (Tt === 2 || Tt === 9) || t.cancelPendingCommit !== null) && (sn(t, 0), $l(
      t,
      yt,
      Me,
      !1
    )), jn(t, l), ((_t & 2) === 0 || t !== At) && (t === At && ((_t & 2) === 0 && (Ta |= l), Gt === 4 && $l(
      t,
      yt,
      Me,
      !1
    )), ol(t));
  }
  function ym(t, e, l) {
    if ((_t & 6) !== 0) throw Error(o(327));
    var a = !l && (e & 127) === 0 && (e & t.expiredLanes) === 0 || En(t, e), n = a ? wy(t, e) : ef(t, e, !0), u = a;
    do {
      if (n === 0) {
        en && !a && $l(t, e, 0, !1);
        break;
      } else {
        if (l = t.current.alternate, u && !Dy(l)) {
          n = ef(t, e, !1), u = !1;
          continue;
        }
        if (n === 2) {
          if (u = e, t.errorRecoveryDisabledLanes & u)
            var i = 0;
          else
            i = t.pendingLanes & -536870913, i = i !== 0 ? i : i & 536870912 ? 536870912 : 0;
          if (i !== 0) {
            e = i;
            t: {
              var f = t;
              n = nu;
              var m = f.current.memoizedState.isDehydrated;
              if (m && (sn(f, i).flags |= 256), i = ef(
                f,
                i,
                !1
              ), i !== 2 && i !== 6) {
                if (Fs && !m) {
                  f.errorRecoveryDisabledLanes |= u, Ta |= u, n = 4;
                  break t;
                }
                u = be, be = n, u !== null && (be === null ? be = u : be.push.apply(
                  be,
                  u
                ));
              }
              n = i;
            }
            if (u = !1, n !== 2) continue;
          }
        }
        if (n === 1) {
          sn(t, 0), $l(t, e, 0, !0);
          break;
        }
        t: {
          switch (a = t, u = n, u) {
            case 0:
            case 1:
              throw Error(o(345));
            case 4:
              if ((e & 4194048) !== e && (e & 62914560) !== e)
                break;
            case 6:
              $l(
                a,
                e,
                Me,
                !Kl
              );
              break t;
            case 2:
              be = null;
              break;
            case 3:
            case 5:
              break;
            default:
              throw Error(o(329));
          }
          if ((e & 62914560) === e && (n = Ci + 300 - _e(), 10 < n)) {
            if ($l(
              a,
              e,
              Me,
              !Kl
            ), Mu(a, 0, !0) !== 0) break t;
            fl = e, a.timeoutHandle = Sf(
              vm.bind(
                null,
                a,
                l,
                be,
                Di,
                Ws,
                e,
                Me,
                Ta,
                ln,
                Kl,
                u,
                "Throttled",
                -0,
                0
              ),
              n
            );
            break t;
          }
          vm(
            a,
            l,
            be,
            Di,
            Ws,
            e,
            Me,
            Ta,
            ln,
            Kl,
            u,
            null,
            -0,
            0
          );
        }
      }
      break;
    } while (!0);
    ol(t);
  }
  function vm(t, e, l, a, n, u, i, f, m, x, j, C, g, T) {
    t.timeoutHandle = -1;
    var L = e.subtreeFlags, $ = (u & 335544064) === u;
    if (C = null, ($ || L & 8192 || (L & 16785408) === 16785408) && (C = {
      stylesheets: null,
      count: 0,
      imgCount: 0,
      imgBytes: 0,
      suspenseyImages: [],
      waitingForImages: !0,
      waitingForViewTransition: !1,
      unsuspend: tl
    }, Ae = null, sm(
      e,
      u,
      C
    ), $ && (L = C, $ = t.containerInfo, $ = ($.nodeType === 9 ? $ : $.ownerDocument).__reactViewTransition, $ != null && (L.count++, L.waitingForViewTransition = !0, L = mu.bind(L), $.finished.then(L, L))), L = (u & 62914560) === u ? Ci - _e() : (u & 4194048) === u ? dm - _e() : 0, L = Bv(
      C,
      L
    ), L !== null)) {
      fl = u, t.cancelPendingCommit = L(
        Tm.bind(
          null,
          t,
          e,
          u,
          l,
          a,
          n,
          i,
          f,
          m,
          x,
          j,
          C,
          null,
          g,
          T
        )
      ), $l(t, u, i, !x);
      return;
    }
    Tm(
      t,
      e,
      u,
      l,
      a,
      n,
      i,
      f,
      m,
      x,
      j,
      C
    );
  }
  function Dy(t) {
    for (var e = t; ; ) {
      var l = e.tag;
      if ((l === 0 || l === 11 || l === 15) && e.flags & 16384 && (l = e.updateQueue, l !== null && (l = l.stores, l !== null)))
        for (var a = 0; a < l.length; a++) {
          var n = l[a], u = n.getSnapshot;
          n = n.value;
          try {
            if (!je(u(), n)) return !1;
          } catch {
            return !1;
          }
        }
      if (l = e.child, e.subtreeFlags & 16384 && l !== null)
        l.return = e, e = l;
      else {
        if (e === t) break;
        for (; e.sibling === null; ) {
          if (e.return === null || e.return === t) return !0;
          e = e.return;
        }
        e.sibling.return = e.return, e = e.sibling;
      }
    }
    return !0;
  }
  function $l(t, e, l, a) {
    e = oo(t, e), e &= ~Mi, e &= ~Ta, t.suspendedLanes |= e, t.pingedLanes &= ~e, a && (t.warmLanes |= e), a = t.expirationTimes;
    for (var n = e; 0 < n; ) {
      var u = 31 - Te(n), i = 1 << u;
      a[u] = -1, n &= ~i;
    }
    l !== 0 && mo(t, l, e);
  }
  function wi() {
    return (_t & 6) === 0 ? (iu(0), !1) : !0;
  }
  function tf() {
    if (mt !== null) {
      if (Tt === 0)
        var t = mt.return;
      else
        t = mt, xl = da = null, ss(t), ka = null, Qn = 0, t = mt;
      for (; t !== null; )
        Yd(t.alternate, t), t = t.return;
      mt = null;
    }
  }
  function sn(t, e) {
    var l = t.timeoutHandle;
    return l !== -1 && (t.timeoutHandle = -1, av(l)), l = t.cancelPendingCommit, l !== null && (t.cancelPendingCommit = null, l()), fl = 0, tf(), At = t, mt = l = pl(t.current, null), yt = e, Tt = 0, Oe = null, Kl = !1, en = En(t, e), Fs = !1, ln = Me = Mi = Ta = kl = Gt = 0, be = nu = null, Ws = !1, jl = oo(t, e), Qu(), l;
  }
  function gm(t, e) {
    it = null, G.H = hi, e === Ka || e === ti ? (e = Tr(), Tt = 3) : e === $c ? (e = Tr(), Tt = 4) : Tt = e === Ns ? 8 : e !== null && typeof e == "object" && typeof e.then == "function" ? 6 : 1, Oe = e, mt === null && (Gt = 1, yi(
      t,
      qe(e, t.current)
    ));
  }
  function pm() {
    var t = ne.current;
    return t === null ? !0 : (yt & 4194048) === yt ? fe === null : (yt & 62914560) === yt || (yt & 536870912) !== 0 ? t === fe : !1;
  }
  function bm() {
    var t = G.H;
    return G.H = hi, t === null ? hi : t;
  }
  function xm() {
    var t = G.A;
    return G.A = Cy, t;
  }
  function Hi() {
    Gt = 4, Kl || (yt & 4194048) !== yt && ne.current !== null || (en = !0), (kl & 134217727) === 0 && (Ta & 134217727) === 0 || At === null || $l(
      At,
      yt,
      Me,
      !1
    );
  }
  function ef(t, e, l) {
    var a = _t;
    _t |= 2;
    var n = bm(), u = xm();
    (At !== t || yt !== e) && (Di = null, sn(t, e)), e = !1;
    var i = Gt;
    t: do
      try {
        if (Tt !== 0 && mt !== null) {
          var f = mt, m = Oe;
          switch (Tt) {
            case 8:
              tf(), i = 6;
              break t;
            case 3:
            case 2:
            case 9:
            case 6:
              ne.current === null && (e = !0);
              var x = Tt;
              if (Tt = 0, Oe = null, fn(t, f, m, x), l && en) {
                i = 0;
                break t;
              }
              break;
            default:
              x = Tt, Tt = 0, Oe = null, fn(t, f, m, x);
          }
        }
        Uy(), i = Gt;
        break;
      } catch (j) {
        gm(t, j);
      }
    while (!0);
    return e && t.shellSuspendCounter++, xl = da = null, _t = a, G.H = n, G.A = u, mt === null && (At = null, yt = 0, Qu()), i;
  }
  function Uy() {
    for (; mt !== null; ) Sm(mt);
  }
  function wy(t, e) {
    var l = _t;
    _t |= 2;
    var a = bm(), n = xm();
    At !== t || yt !== e ? (Di = null, Ri = _e() + 500, sn(t, e)) : en = En(
      t,
      e
    );
    t: do
      try {
        if (Tt !== 0 && mt !== null) {
          e = mt;
          var u = Oe;
          e: switch (Tt) {
            case 1:
              Tt = 0, Oe = null, fn(t, e, u, 1);
              break;
            case 2:
            case 9:
              if (_r(u)) {
                Tt = 0, Oe = null, _m(e);
                break;
              }
              e = function() {
                Tt !== 2 && Tt !== 9 || At !== t || (Tt = 7), ol(t);
              }, u.then(e, e);
              break t;
            case 3:
              Tt = 7;
              break t;
            case 4:
              Tt = 5;
              break t;
            case 7:
              _r(u) ? (Tt = 0, Oe = null, _m(e)) : (Tt = 0, Oe = null, fn(t, e, u, 7));
              break;
            case 5:
              var i = null;
              switch (mt.tag) {
                case 26:
                  i = mt.memoizedState;
                case 5:
                case 27:
                  var f = mt;
                  if (i ? mh(i) : f.stateNode.complete) {
                    Tt = 0, Oe = null;
                    var m = f.sibling;
                    if (m !== null) mt = m;
                    else {
                      var x = f.return;
                      x !== null ? (mt = x, Bi(x)) : mt = null;
                    }
                    break e;
                  }
              }
              Tt = 0, Oe = null, fn(t, e, u, 5);
              break;
            case 6:
              Tt = 0, Oe = null, fn(t, e, u, 6);
              break;
            case 8:
              tf(), Gt = 6;
              break t;
            default:
              throw Error(o(462));
          }
        }
        Hy();
        break;
      } catch (j) {
        gm(t, j);
      }
    while (!0);
    return xl = da = null, G.H = a, G.A = n, _t = l, mt !== null ? 0 : (At = null, yt = 0, Qu(), Gt);
  }
  function Hy() {
    for (; mt !== null && !Ph(); )
      Sm(mt);
  }
  function Sm(t) {
    var e = Bd(t.alternate, t, jl);
    t.memoizedProps = t.pendingProps, e === null ? Bi(t) : mt = e;
  }
  function _m(t) {
    var e = t, l = e.alternate;
    switch (e.tag) {
      case 15:
      case 0:
        e = Md(
          l,
          e,
          e.pendingProps,
          e.type,
          void 0,
          yt
        );
        break;
      case 11:
        e = Md(
          l,
          e,
          e.pendingProps,
          e.type.render,
          e.ref,
          yt
        );
        break;
      case 5:
        ss(e);
        var a = e;
        a === It && (ot ? ($u(a), a.tag === 5 && a.stateNode != null && (Mt = a.stateNode)) : ($u(a), ot = !0));
      default:
        Yd(l, e), e = mt = rr(e, jl), e = Bd(l, e, jl);
    }
    t.memoizedProps = t.pendingProps, e === null ? Bi(t) : mt = e;
  }
  function fn(t, e, l, a) {
    xl = da = null, ss(e), ka = null, Qn = 0;
    var n = e.return;
    try {
      if (Ny(
        t,
        n,
        e,
        l,
        yt
      )) {
        Gt = 1, yi(
          t,
          qe(l, t.current)
        ), mt = null;
        return;
      }
    } catch (u) {
      if (n !== null) throw mt = n, u;
      Gt = 1, yi(
        t,
        qe(l, t.current)
      ), mt = null;
      return;
    }
    e.flags & 32768 ? (ot || a === 1 ? t = !0 : en || (yt & 536870912) !== 0 ? t = !1 : (Kl = t = !0, (a === 2 || a === 9 || a === 3 || a === 6) && (a = ne.current, a !== null && a.tag === 13 && (a.flags |= 16384))), Nm(e, t)) : Bi(e);
  }
  function Bi(t) {
    var e = t;
    do {
      if ((e.flags & 32768) !== 0) {
        Nm(
          e,
          Kl
        );
        return;
      }
      t = e.return;
      var l = zy(
        e.alternate,
        e,
        jl
      );
      if (l !== null) {
        mt = l;
        return;
      }
      if (e = e.sibling, e !== null) {
        mt = e;
        return;
      }
      mt = e = t;
    } while (e !== null);
    Gt === 0 && (Gt = 5);
  }
  function Nm(t, e) {
    do {
      var l = Ay(t.alternate, t);
      if (l !== null) {
        l.flags &= 32767, mt = l;
        return;
      }
      if (l = t.return, l !== null && (l.flags |= 32768, l.subtreeFlags = 0, l.deletions = null), !e && (t = t.sibling, t !== null)) {
        mt = t;
        return;
      }
      mt = t = l;
    } while (t !== null);
    Gt = 6, mt = null;
  }
  function Tm(t, e, l, a, n, u, i, f, m, x, j, C) {
    t.cancelPendingCommit = null;
    do
      qi();
    while (Bt !== 0);
    if ((_t & 6) !== 0) throw Error(o(327));
    if (e !== null) {
      if (e === t.current) throw Error(o(177));
      t === At && (mt = At = null, yt = 0), Ea = e, We = t, fl = l, Ps = n, mm = a, By(
        t,
        e,
        l,
        i,
        f,
        m,
        C
      );
    }
  }
  function By(t, e, l, a, n, u, i) {
    var f = e.lanes | e.childLanes;
    if (Is = f, f |= Hc, f0(
      t,
      l,
      f,
      a,
      n,
      u
    ), nn = null, (l & 335544064) === l ? (un = ry(t), a = 10262) : (un = null, a = 10256), (e.subtreeFlags & a) !== 0 || (e.flags & a) !== 0 ? (t.callbackNode = null, t.callbackPriority = 0, Qy(ju, function() {
      return uf(), null;
    })) : (t.callbackNode = null, t.callbackPriority = 0), Ni = !1, a = (e.flags & 13878) !== 0, (e.subtreeFlags & 13878) !== 0 || a) {
      a = G.T, G.T = null, n = W.p, W.p = 2, u = _t, _t |= 4;
      try {
        Oy(t, e, l);
      } finally {
        _t = u, W.p = n, G.T = a;
      }
    }
    Bt = 1, Ni ? an = fv(
      i,
      t.containerInfo,
      un,
      lf,
      af,
      Yy,
      nf,
      uf,
      qy
    ) : (lf(), af(), nf());
  }
  function qy(t) {
    if (Bt !== 0) {
      var e = We.onRecoverableError;
      e(t, { componentStack: null });
    }
  }
  function Yy() {
    Bt === 3 && (Bt = 0, im(Ea, We), Bt = 4);
  }
  function lf() {
    if (Bt === 1) {
      Bt = 0;
      var t = We, e = Ea, l = fl, a = (e.flags & 13878) !== 0;
      if ((e.subtreeFlags & 13878) !== 0 || a) {
        a = G.T, G.T = null;
        var n = W.p;
        W.p = 2;
        var u = _t;
        _t |= 4;
        try {
          eu = ji = !1, nm(e, t, l), l = pf;
          var i = er(t.containerInfo), f = l.focusedElem, m = l.selectionRange;
          if (i !== f && f && f.ownerDocument && tr(
            f.ownerDocument.documentElement,
            f
          )) {
            if (m !== null && Cc(f)) {
              var x = m.start, j = m.end;
              if (j === void 0 && (j = x), "selectionStart" in f)
                f.selectionStart = x, f.selectionEnd = Math.min(
                  j,
                  f.value.length
                );
              else {
                var C = f.ownerDocument || document, g = C && C.defaultView || window;
                if (g.getSelection) {
                  var T = g.getSelection(), L = f.textContent.length, $ = Math.min(m.start, L), ct = m.end === void 0 ? $ : Math.min(m.end, L);
                  !T.extend && $ > ct && (i = ct, ct = $, $ = i);
                  var b = Po(
                    f,
                    $
                  ), v = Po(
                    f,
                    ct
                  );
                  if (b && v && (T.rangeCount !== 1 || T.anchorNode !== b.node || T.anchorOffset !== b.offset || T.focusNode !== v.node || T.focusOffset !== v.offset)) {
                    var S = C.createRange();
                    S.setStart(b.node, b.offset), T.removeAllRanges(), $ > ct ? (T.addRange(S), T.extend(v.node, v.offset)) : (S.setEnd(v.node, v.offset), T.addRange(S));
                  }
                }
              }
            }
            for (C = [], T = f; T = T.parentNode; )
              T.nodeType === 1 && C.push({
                element: T,
                left: T.scrollLeft,
                top: T.scrollTop
              });
            for (typeof f.focus == "function" && f.focus(), f = 0; f < C.length; f++) {
              var O = C[f];
              O.element.scrollLeft = O.left, O.element.scrollTop = O.top;
            }
          }
          gn = !!gf, pf = gf = null;
        } finally {
          _t = u, W.p = n, G.T = a;
        }
      }
      t.current = e, Bt = 2;
    }
  }
  function af() {
    if (Bt === 2) {
      Bt = 0;
      var t = We, e = Ea, l = (e.flags & 8772) !== 0;
      if ((e.subtreeFlags & 8772) !== 0 || l) {
        l = G.T, G.T = null;
        var a = W.p;
        W.p = 2;
        var n = _t;
        _t |= 4;
        try {
          Id(t, e.alternate, e);
        } finally {
          _t = n, W.p = a, G.T = l;
        }
      }
      Bt = 3;
    }
  }
  function nf() {
    if (Bt === 4 || Bt === 3) {
      Bt = 0;
      var t = an;
      an = null, t0();
      var e = We, l = Ea, a = fl, n = mm, u = (a & 335544064) === a ? 10262 : 10256;
      if ((l.subtreeFlags & u) !== 0 || (l.flags & u) !== 0 ? Bt = 5 : (Bt = 0, Ea = We = null, Em(e, e.pendingLanes)), u = e.pendingLanes, u === 0 && (Jl = null), mc(a), l = l.stateNode, Ne && typeof Ne.onCommitFiberRoot == "function")
        try {
          Ne.onCommitFiberRoot(
            Tn,
            l,
            void 0,
            (l.current.flags & 128) === 128
          );
        } catch {
        }
      if (n !== null) {
        l = G.T, u = W.p, W.p = 2, G.T = null;
        try {
          for (var i = e.onRecoverableError, f = 0; f < n.length; f++) {
            var m = n[f];
            i(m.value, {
              componentStack: m.stack
            });
          }
        } finally {
          G.T = l, W.p = u;
        }
      }
      if (n = nn, i = un, un = null, n !== null && (nn = null, i === null && (i = []), t !== null))
        for (m = 0; m < n.length; m++)
          l = (0, n[m])(
            i
          ), l !== void 0 && t.finished.finally(l);
      (fl & 3) !== 0 && qi(), ol(e), u = e.pendingLanes, (a & 261930) !== 0 && (u & 42) !== 0 ? e === Ui ? uu++ : (uu = 0, Ui = e) : (uu = 0, Ui = null), iu(0);
    }
  }
  function Em(t, e) {
    (t.pooledCacheLanes &= e) === 0 && (e = t.pooledCache, e != null && (t.pooledCache = null, Ln(e)));
  }
  function qi() {
    return an !== null && (an.skipTransition(), an = null), lf(), af(), nf(), uf();
  }
  function uf() {
    if (Bt !== 5) return !1;
    var t = We, e = Is;
    Is = 0;
    var l = mc(fl), a = G.T, n = W.p;
    try {
      W.p = 32 > l ? 32 : l, G.T = null, l = Ps, Ps = null;
      var u = We, i = fl;
      if (Bt = 0, Ea = We = null, fl = 0, (_t & 6) !== 0) throw Error(o(331));
      var f = _t;
      if (_t |= 4, om(u.current), cm(
        u,
        u.current,
        i,
        l
      ), _t = f, iu(0, !1), Ne && typeof Ne.onPostCommitFiberRoot == "function")
        try {
          Ne.onPostCommitFiberRoot(Tn, u);
        } catch {
        }
      return !0;
    } finally {
      W.p = n, G.T = a, Em(t, e);
    }
  }
  function jm(t, e, l) {
    e = qe(l, e), e = _s(t.stateNode, e, 2), t = Ll(t, e, 2), t !== null && (jn(t, 2), ol(t));
  }
  function Et(t, e, l) {
    if (t.tag === 3)
      jm(t, t, l);
    else
      for (; e !== null; ) {
        if (e.tag === 3) {
          jm(
            e,
            t,
            l
          );
          break;
        } else if (e.tag === 1) {
          var a = e.stateNode;
          if (typeof e.type.getDerivedStateFromError == "function" || typeof a.componentDidCatch == "function" && (Jl === null || !Jl.has(a))) {
            t = qe(l, t), l = _d(2), a = Ll(e, l, 2), a !== null && (Nd(
              l,
              a,
              e,
              t
            ), jn(a, 2), ol(a));
            break;
          }
        }
        e = e.return;
      }
  }
  function cf(t, e, l) {
    var a = t.pingCache;
    if (a === null) {
      a = t.pingCache = new Ry();
      var n = /* @__PURE__ */ new Set();
      a.set(e, n);
    } else
      n = a.get(e), n === void 0 && (n = /* @__PURE__ */ new Set(), a.set(e, n));
    n.has(l) || (Fs = !0, n.add(l), t = Ly.bind(null, t, e, l), e.then(t, t));
  }
  function Ly(t, e, l) {
    var a = t.pingCache;
    a !== null && a.delete(e), t.pingedLanes |= t.suspendedLanes & l, t.warmLanes &= ~l, At === t && (yt & l) === l && ((Gt === 4 || Gt === 3 && (yt & 62914560) === yt && 300 > _e() - Ci) && (_t & 2) === 0 ? sn(t, 0) : Mi |= l, ln === yt && (ln = 0)), ol(t);
  }
  function zm(t, e) {
    e === 0 && (e = ro()), t = fa(t, e), t !== null && (jn(t, e), ol(t));
  }
  function Xy(t) {
    var e = t.memoizedState, l = 0;
    e !== null && (l = e.retryLane), zm(t, l);
  }
  function Gy(t, e) {
    var l = 0;
    switch (t.tag) {
      case 31:
      case 13:
        var a = t.stateNode, n = t.memoizedState;
        n !== null && (l = n.retryLane);
        break;
      case 19:
        a = t.stateNode;
        break;
      case 22:
        a = t.stateNode._retryCache;
        break;
      default:
        throw Error(o(314));
    }
    a !== null && a.delete(e), zm(t, l);
  }
  function Qy(t, e) {
    return fc(t, e);
  }
  var on = null, rn = null, sf = !1, Yi = !1, ff = !1, Fl = 0;
  function ol(t) {
    t !== rn && t.next === null && (rn === null ? on = rn = t : rn = rn.next = t), Yi = !0, sf || (sf = !0, Zy());
  }
  function iu(t, e) {
    if (!ff && Yi) {
      ff = !0;
      do
        for (var l = !1, a = on; a !== null; ) {
          if (t !== 0) {
            var n = a.pendingLanes;
            if (n === 0) var u = 0;
            else {
              var i = a.suspendedLanes, f = a.pingedLanes;
              u = (1 << 31 - Te(42 | t) + 1) - 1, u &= n & ~(i & ~f), u = u & 201326741 ? u & 201326741 | 1 : u ? u | 2 : 0;
            }
            u !== 0 && (l = !0, Cm(a, u));
          } else
            u = yt, u = Mu(
              a,
              a === At ? u : 0,
              a.cancelPendingCommit !== null || a.timeoutHandle !== -1
            ), (u & 3) === 0 || En(a, u) || (l = !0, Cm(a, u));
          a = a.next;
        }
      while (l);
      ff = !1;
    }
  }
  function Vy() {
    Am();
  }
  function Am() {
    Yi = sf = !1;
    var t = 0;
    Fl !== 0 && lv() && (t = Fl);
    for (var e = _e(), l = null, a = on; a !== null; ) {
      var n = a.next, u = Om(a, e);
      u === 0 ? (a.next = null, l === null ? on = n : l.next = n, n === null && (rn = l)) : (l = a, (t !== 0 || (u & 3) !== 0) && (Yi = !0)), a = n;
    }
    Bt !== 0 && Bt !== 5 || iu(t), Fl !== 0 && (Fl = 0);
  }
  function Om(t, e) {
    for (var l = t.suspendedLanes, a = t.pingedLanes, n = t.expirationTimes, u = t.pendingLanes & -62914561; 0 < u; ) {
      var i = 31 - Te(u), f = 1 << i, m = n[i];
      m === -1 ? ((f & l) === 0 || (f & a) !== 0) && (n[i] = s0(f, e)) : m <= e && (t.expiredLanes |= f), u &= ~f;
    }
    if (e = At, l = yt, l = Mu(
      t,
      t === e ? l : 0,
      t.cancelPendingCommit !== null || t.timeoutHandle !== -1
    ), a = t.callbackNode, l === 0 || t === e && (Tt === 2 || Tt === 9) || t.cancelPendingCommit !== null)
      return a !== null && a !== null && oc(a), t.callbackNode = null, t.callbackPriority = 0;
    if ((l & 3) === 0 || En(t, l)) {
      if (e = l & -l, e === t.callbackPriority) return e;
      switch (a !== null && oc(a), mc(l)) {
        case 2:
        case 8:
          l = so;
          break;
        case 32:
          l = ju;
          break;
        case 268435456:
          l = fo;
          break;
        default:
          l = ju;
      }
      return a = Mm.bind(null, t), l = fc(l, a), t.callbackPriority = e, t.callbackNode = l, e;
    }
    return a !== null && a !== null && oc(a), t.callbackPriority = 2, t.callbackNode = null, 2;
  }
  function Mm(t, e) {
    if (Bt !== 0 && Bt !== 5)
      return t.callbackNode = null, t.callbackPriority = 0, null;
    var l = t.callbackNode;
    if (qi() && t.callbackNode !== l)
      return null;
    var a = yt;
    return a = Mu(
      t,
      t === At ? a : 0,
      t.cancelPendingCommit !== null || t.timeoutHandle !== -1
    ), a === 0 ? null : (ym(t, a, e), Om(t, _e()), t.callbackNode != null && t.callbackNode === l ? Mm.bind(null, t) : null);
  }
  function Cm(t, e) {
    if (qi()) return null;
    ym(t, e, !0);
  }
  function Zy() {
    nv(function() {
      (_t & 6) !== 0 ? fc(
        co,
        Vy
      ) : Am();
    });
  }
  function of() {
    if (Fl === 0) {
      var t = ya;
      t === 0 && (t = zu, zu <<= 1, (zu & 261888) === 0 && (zu = 256)), Fl = t;
    }
    return Fl;
  }
  function Rm(t) {
    return t == null || typeof t == "symbol" || typeof t == "boolean" ? null : typeof t == "function" ? t : wu(t);
  }
  function Ky(t, e, l, a, n) {
    if (e === "submit" && l && l.stateNode === n) {
      var u = Rm(
        (n[ye] || null).action
      ), i = a.submitter;
      i && (e = (e = i[ye] || null) ? Rm(e.formAction) : i.getAttribute("formAction"), e !== null && (u = e, i = null));
      var f = new Yu(
        "action",
        "action",
        null,
        a,
        n
      );
      t.push({
        event: f,
        listeners: [
          {
            instance: null,
            listener: function() {
              if (a.defaultPrevented) {
                if (Fl !== 0) {
                  var m = new FormData(n, i);
                  gs(
                    l,
                    {
                      pending: !0,
                      data: m,
                      method: n.method,
                      action: u
                    },
                    null,
                    m
                  );
                }
              } else
                typeof u == "function" && (f.preventDefault(), m = new FormData(n, i), gs(
                  l,
                  {
                    pending: !0,
                    data: m,
                    method: n.method,
                    action: u
                  },
                  u,
                  m
                ));
            },
            currentTarget: n
          }
        ]
      });
    }
  }
  for (var rf = 0; rf < wc.length; rf++) {
    var df = wc[rf], ky = df.toLowerCase(), Jy = df[0].toUpperCase() + df.slice(1);
    ke(
      ky,
      "on" + Jy
    );
  }
  ke(nr, "onAnimationEnd"), ke(ur, "onAnimationIteration"), ke(ir, "onAnimationStart"), ke("dblclick", "onDoubleClick"), ke("focusin", "onFocus"), ke("focusout", "onBlur"), ke(ay, "onTransitionRun"), ke(ny, "onTransitionStart"), ke(uy, "onTransitionCancel"), ke(cr, "onTransitionEnd"), Ra("onMouseEnter", ["mouseout", "mouseover"]), Ra("onMouseLeave", ["mouseout", "mouseover"]), Ra("onPointerEnter", ["pointerout", "pointerover"]), Ra("onPointerLeave", ["pointerout", "pointerover"]), ia(
    "onChange",
    "change click focusin focusout input keydown keyup selectionchange".split(" ")
  ), ia(
    "onSelect",
    "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(
      " "
    )
  ), ia("onBeforeInput", [
    "compositionend",
    "keypress",
    "textInput",
    "paste"
  ]), ia(
    "onCompositionEnd",
    "compositionend focusout keydown keypress keyup mousedown".split(" ")
  ), ia(
    "onCompositionStart",
    "compositionstart focusout keydown keypress keyup mousedown".split(" ")
  ), ia(
    "onCompositionUpdate",
    "compositionupdate focusout keydown keypress keyup mousedown".split(" ")
  );
  var cu = "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(
    " "
  ), $y = new Set(
    "beforetoggle cancel close invalid load scroll scrollend toggle".split(" ").concat(cu)
  );
  function Dm(t, e) {
    e = (e & 4) !== 0;
    for (var l = 0; l < t.length; l++) {
      var a = t[l], n = a.event;
      a = a.listeners;
      t: {
        var u = void 0;
        if (e)
          for (var i = a.length - 1; 0 <= i; i--) {
            var f = a[i], m = f.instance, x = f.currentTarget;
            if (f = f.listener, m !== u && n.isPropagationStopped())
              break t;
            u = f, n.currentTarget = x;
            try {
              u(n);
            } catch (j) {
              Gu(j);
            }
            n.currentTarget = null, u = m;
          }
        else
          for (i = 0; i < a.length; i++) {
            if (f = a[i], m = f.instance, x = f.currentTarget, f = f.listener, m !== u && n.isPropagationStopped())
              break t;
            u = f, n.currentTarget = x;
            try {
              u(n);
            } catch (j) {
              Gu(j);
            }
            n.currentTarget = null, u = m;
          }
      }
    }
  }
  function ht(t, e) {
    var l = e[po];
    l === void 0 && (l = e[po] = /* @__PURE__ */ new Set());
    var a = t + "__bubble";
    l.has(a) || (Um(e, t, 2, !1), l.add(a));
  }
  function mf(t, e, l) {
    var a = 0;
    e && (a |= 4), Um(
      l,
      t,
      a,
      e
    );
  }
  var Li = "_reactListening" + Math.random().toString(36).slice(2);
  function hf(t) {
    if (!t[Li]) {
      t[Li] = !0, So.forEach(function(l) {
        l !== "selectionchange" && ($y.has(l) || mf(l, !1, t), mf(l, !0, t));
      });
      var e = t.nodeType === 9 ? t : t.ownerDocument;
      e === null || e[Li] || (e[Li] = !0, mf("selectionchange", !1, e));
    }
  }
  function Um(t, e, l, a) {
    switch (Nh(e)) {
      case 2:
        var n = Xv;
        break;
      case 8:
        n = Gv;
        break;
      default:
        n = Uf;
    }
    l = n.bind(
      null,
      e,
      l,
      t
    ), n = void 0, !Sc || e !== "touchstart" && e !== "touchmove" && e !== "wheel" || (n = !0), a ? n !== void 0 ? t.addEventListener(e, l, {
      capture: !0,
      passive: n
    }) : t.addEventListener(e, l, !0) : n !== void 0 ? t.addEventListener(e, l, {
      passive: n
    }) : t.addEventListener(e, l, !1);
  }
  function yf(t, e, l, a, n) {
    var u = a;
    if ((e & 1) === 0 && (e & 2) === 0 && a !== null)
      t: for (; ; ) {
        if (a === null) return;
        var i = a.tag;
        if (i === 3 || i === 4) {
          var f = a.stateNode.containerInfo;
          if (f === n) break;
          if (i === 4)
            for (i = a.return; i !== null; ) {
              var m = i.tag;
              if ((m === 3 || m === 4) && i.stateNode.containerInfo === n)
                return;
              i = i.return;
            }
          for (; f !== null; ) {
            if (i = ua(f), i === null) return;
            if (m = i.tag, m === 5 || m === 6 || m === 26 || m === 27) {
              a = u = i;
              continue t;
            }
            f = f.parentNode;
          }
        }
        a = a.return;
      }
    Uo(function() {
      var x = u, j = bc(l), C = [];
      t: {
        var g = sr.get(t);
        if (g !== void 0) {
          var T = Yu, L = t;
          switch (t) {
            case "keypress":
              if (Bu(l) === 0) break t;
            case "keydown":
            case "keyup":
              T = D0;
              break;
            case "focusin":
              L = "focus", T = Ec;
              break;
            case "focusout":
              L = "blur", T = Ec;
              break;
            case "beforeblur":
            case "afterblur":
              T = Ec;
              break;
            case "click":
              if (l.button === 2) break t;
            case "auxclick":
            case "dblclick":
            case "mousedown":
            case "mousemove":
            case "mouseup":
            case "mouseout":
            case "mouseover":
            case "contextmenu":
              T = Bo;
              break;
            case "drag":
            case "dragend":
            case "dragenter":
            case "dragexit":
            case "dragleave":
            case "dragover":
            case "dragstart":
            case "drop":
              T = S0;
              break;
            case "touchcancel":
            case "touchend":
            case "touchmove":
            case "touchstart":
              T = q0;
              break;
            case nr:
            case ur:
            case ir:
              T = T0;
              break;
            case cr:
              T = L0;
              break;
            case "scroll":
            case "scrollend":
              T = b0;
              break;
            case "wheel":
              T = G0;
              break;
            case "copy":
            case "cut":
            case "paste":
              T = j0;
              break;
            case "gotpointercapture":
            case "lostpointercapture":
            case "pointercancel":
            case "pointerdown":
            case "pointermove":
            case "pointerout":
            case "pointerover":
            case "pointerup":
              T = Yo;
              break;
            case "submit":
              T = H0;
              break;
            case "toggle":
            case "beforetoggle":
              T = V0;
          }
          var $ = (e & 4) !== 0, ct = !$ && (t === "scroll" || t === "scrollend"), b = $ ? g !== null ? g + "Capture" : null : g;
          $ = [];
          for (var v = x, S; v !== null; ) {
            var O = v;
            if (S = O.stateNode, O = O.tag, O !== 5 && O !== 26 && O !== 27 || S === null || b === null || (O = On(v, b), O != null && $.push(
              su(v, O, S)
            )), ct) break;
            v = v.return;
          }
          0 < $.length && (g = new T(
            g,
            L,
            null,
            l,
            j
          ), C.push({ event: g, listeners: $ }));
        }
      }
      if ((e & 7) === 0) {
        t: {
          if (T = t === "mouseover" || t === "pointerover", g = t === "mouseout" || t === "pointerout", T && l !== pc && (L = l.relatedTarget || l.fromElement) && (ua(L) || L[Oa]))
            break t;
          (g || T) && (L = j.window === j ? j : (T = j.ownerDocument) ? T.defaultView || T.parentWindow : window, g ? (T = l.relatedTarget || l.toElement, g = x, T = T ? ua(T) : null, T !== null && (ct = D(T), $ = T.tag, T !== ct || $ !== 5 && $ !== 27 && $ !== 6) && (T = null)) : (g = null, T = x), g !== T && ($ = Bo, O = "onMouseLeave", b = "onMouseEnter", v = "mouse", (t === "pointerout" || t === "pointerover") && ($ = Yo, O = "onPointerLeave", b = "onPointerEnter", v = "pointer"), ct = g == null ? L : An(g), S = T == null ? L : An(T), L = new $(
            O,
            v + "leave",
            g,
            l,
            j
          ), L.target = ct, L.relatedTarget = S, O = null, ua(j) === x && ($ = new $(
            b,
            v + "enter",
            T,
            l,
            j
          ), $.target = S, $.relatedTarget = ct, O = $), ct = O, $ = g && T ? dt(
            g,
            T,
            Fy
          ) : null, g !== null && wm(
            C,
            L,
            g,
            $,
            !1
          ), T !== null && ct !== null && wm(
            C,
            ct,
            T,
            $,
            !0
          )));
        }
        t: {
          if (g = x ? An(x) : window, T = g.nodeName && g.nodeName.toLowerCase(), T === "select" || T === "input" && g.type === "file")
            var Z = ko;
          else if (Zo(g))
            if (Jo)
              Z = ty;
            else {
              Z = I0;
              var vt = W0;
            }
          else
            T = g.nodeName, !T || T.toLowerCase() !== "input" || g.type !== "checkbox" && g.type !== "radio" ? x && gc(x.elementType) && (Z = ko) : Z = P0;
          if (Z && (Z = Z(t, x))) {
            Ko(
              C,
              Z,
              l,
              j
            );
            break t;
          }
          vt && vt(t, g, x);
        }
        switch (vt = x ? An(x) : window, t) {
          case "focusin":
            (Zo(vt) || vt.contentEditable === "true") && (qa = vt, Rc = x, Bn = null);
            break;
          case "focusout":
            Bn = Rc = qa = null;
            break;
          case "mousedown":
            Dc = !0;
            break;
          case "contextmenu":
          case "mouseup":
          case "dragend":
            Dc = !1, lr(C, l, j);
            break;
          case "selectionchange":
            if (ly) break;
          case "keydown":
          case "keyup":
            lr(C, l, j);
        }
        var tt;
        if (zc)
          t: {
            switch (t) {
              case "compositionstart":
                var lt = "onCompositionStart";
                break t;
              case "compositionend":
                lt = "onCompositionEnd";
                break t;
              case "compositionupdate":
                lt = "onCompositionUpdate";
                break t;
            }
            lt = void 0;
          }
        else
          Ba ? Qo(t, l) && (lt = "onCompositionEnd") : t === "keydown" && l.keyCode === 229 && (lt = "onCompositionStart");
        lt && (Lo && l.locale !== "ko" && (Ba || lt !== "onCompositionStart" ? lt === "onCompositionEnd" && Ba && (tt = wo()) : (Cl = j, _c = "value" in Cl ? Cl.value : Cl.textContent, Ba = !0)), vt = Xi(x, lt), 0 < vt.length && (lt = new qo(
          lt,
          t,
          null,
          l,
          j
        ), C.push({ event: lt, listeners: vt }), tt ? lt.data = tt : (tt = Vo(l), tt !== null && (lt.data = tt)))), (tt = K0 ? k0(t, l) : J0(t, l)) && (lt = Xi(x, "onBeforeInput"), 0 < lt.length && (vt = new qo(
          "onBeforeInput",
          "beforeinput",
          null,
          l,
          j
        ), C.push({
          event: vt,
          listeners: lt
        }), vt.data = tt)), Ky(
          C,
          t,
          x,
          l,
          j
        );
      }
      Dm(C, e);
    });
  }
  function su(t, e, l) {
    return {
      instance: t,
      listener: e,
      currentTarget: l
    };
  }
  function Xi(t, e) {
    for (var l = e + "Capture", a = []; t !== null; ) {
      var n = t, u = n.stateNode;
      if (n = n.tag, n !== 5 && n !== 26 && n !== 27 || u === null || (n = On(t, l), n != null && a.unshift(
        su(t, n, u)
      ), n = On(t, e), n != null && a.push(
        su(t, n, u)
      )), t.tag === 3) return a;
      t = t.return;
    }
    return [];
  }
  function Fy(t) {
    if (t === null) return null;
    do
      t = t.return;
    while (t && t.tag !== 5 && t.tag !== 27);
    return t || null;
  }
  function wm(t, e, l, a, n) {
    for (var u = e._reactName, i = []; l !== null && l !== a; ) {
      var f = l, m = f.alternate, x = f.stateNode;
      if (f = f.tag, m !== null && m === a) break;
      f !== 5 && f !== 26 && f !== 27 || x === null || (m = x, n ? (x = On(l, u), x != null && i.unshift(
        su(l, x, m)
      )) : n || (x = On(l, u), x != null && i.push(
        su(l, x, m)
      ))), l = l.return;
    }
    i.length !== 0 && t.push({ event: e, listeners: i });
  }
  var Wy = /\r\n?/g, Iy = /\u0000|\uFFFD/g;
  function Hm(t) {
    return (typeof t == "string" ? t : "" + t).replace(Wy, `
`).replace(Iy, "");
  }
  function Bm(t, e) {
    return e = Hm(e), Hm(t) === e;
  }
  function jt(t, e, l, a, n, u) {
    switch (l) {
      case "children":
        if (typeof a == "string")
          e === "body" || e === "textarea" && a === "" || Ua(t, a);
        else if (typeof a == "number" || typeof a == "bigint")
          e !== "body" && Ua(t, "" + a);
        else return;
        break;
      case "className":
        Uu(t, "class", a);
        break;
      case "tabIndex":
        Uu(t, "tabindex", a);
        break;
      case "dir":
      case "role":
      case "viewBox":
      case "width":
      case "height":
        Uu(t, l, a);
        break;
      case "style":
        Ro(t, a, u);
        return;
      case "data":
        if (e !== "object") {
          Uu(t, "data", a);
          break;
        }
      case "src":
      case "href":
        if (a === "" && (e !== "a" || l !== "href")) {
          t.removeAttribute(l);
          break;
        }
        if (a == null || typeof a == "function" || typeof a == "symbol" || typeof a == "boolean") {
          t.removeAttribute(l);
          break;
        }
        a = wu(a), t.setAttribute(l, a);
        break;
      case "action":
      case "formAction":
        if (typeof a == "function") {
          t.setAttribute(
            l,
            "javascript:throw new Error('A React form was unexpectedly submitted. If you called form.submit() manually, consider using form.requestSubmit() instead. If you\\'re trying to use event.stopPropagation() in a submit event handler, consider also calling event.preventDefault().')"
          );
          break;
        } else
          typeof u == "function" && (l === "formAction" ? (e !== "input" && jt(t, e, "name", n.name, n, null), jt(
            t,
            e,
            "formEncType",
            n.formEncType,
            n,
            null
          ), jt(
            t,
            e,
            "formMethod",
            n.formMethod,
            n,
            null
          ), jt(
            t,
            e,
            "formTarget",
            n.formTarget,
            n,
            null
          )) : (jt(t, e, "encType", n.encType, n, null), jt(t, e, "method", n.method, n, null), jt(t, e, "target", n.target, n, null)));
        if (a == null || typeof a == "symbol" || typeof a == "boolean") {
          t.removeAttribute(l);
          break;
        }
        a = wu(a), t.setAttribute(l, a);
        break;
      case "onClick":
        a != null && (t.onclick = tl);
        return;
      case "onScroll":
        a != null && ht("scroll", t);
        return;
      case "onScrollEnd":
        a != null && ht("scrollend", t);
        return;
      case "dangerouslySetInnerHTML":
        if (a != null) {
          if (typeof a != "object" || !("__html" in a))
            throw Error(o(61));
          if (l = a.__html, l != null) {
            if (n.children != null) throw Error(o(60));
            u?.__html !== l && (t.innerHTML = l);
          }
        }
        break;
      case "multiple":
        t.multiple = a && typeof a != "function" && typeof a != "symbol";
        break;
      case "muted":
        t.muted = a && typeof a != "function" && typeof a != "symbol";
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "defaultValue":
      case "defaultChecked":
      case "innerHTML":
      case "ref":
        break;
      case "autoFocus":
        break;
      case "xlinkHref":
        if (a == null || typeof a == "function" || typeof a == "boolean" || typeof a == "symbol") {
          t.removeAttribute("xlink:href");
          break;
        }
        l = wu(a), t.setAttributeNS(
          "http://www.w3.org/1999/xlink",
          "xlink:href",
          l
        );
        break;
      case "contentEditable":
      case "spellCheck":
      case "draggable":
      case "value":
      case "autoReverse":
      case "externalResourcesRequired":
      case "focusable":
      case "preserveAlpha":
        a != null && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(l, a) : t.removeAttribute(l);
        break;
      case "inert":
      case "allowFullScreen":
      case "async":
      case "autoPlay":
      case "controls":
      case "credentialless":
      case "default":
      case "defer":
      case "disabled":
      case "disablePictureInPicture":
      case "disableRemotePlayback":
      case "formNoValidate":
      case "hidden":
      case "loop":
      case "noModule":
      case "noValidate":
      case "open":
      case "playsInline":
      case "readOnly":
      case "required":
      case "reversed":
      case "scoped":
      case "seamless":
      case "itemScope":
        a && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(l, "") : t.removeAttribute(l);
        break;
      case "capture":
      case "download":
        a === !0 ? t.setAttribute(l, "") : a !== !1 && a != null && typeof a != "function" && typeof a != "symbol" ? t.setAttribute(l, a) : t.removeAttribute(l);
        break;
      case "cols":
      case "rows":
      case "size":
      case "span":
        a != null && typeof a != "function" && typeof a != "symbol" && !isNaN(a) && 1 <= a ? t.setAttribute(l, a) : t.removeAttribute(l);
        break;
      case "rowSpan":
      case "start":
        a == null || typeof a == "function" || typeof a == "symbol" || isNaN(a) ? t.removeAttribute(l) : t.setAttribute(l, a);
        break;
      case "popover":
        ht("beforetoggle", t), ht("toggle", t), Du(t, "popover", a);
        break;
      case "xlinkActuate":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:actuate",
          a
        );
        break;
      case "xlinkArcrole":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:arcrole",
          a
        );
        break;
      case "xlinkRole":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:role",
          a
        );
        break;
      case "xlinkShow":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:show",
          a
        );
        break;
      case "xlinkTitle":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:title",
          a
        );
        break;
      case "xlinkType":
        hl(
          t,
          "http://www.w3.org/1999/xlink",
          "xlink:type",
          a
        );
        break;
      case "xmlBase":
        hl(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:base",
          a
        );
        break;
      case "xmlLang":
        hl(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:lang",
          a
        );
        break;
      case "xmlSpace":
        hl(
          t,
          "http://www.w3.org/XML/1998/namespace",
          "xml:space",
          a
        );
        break;
      case "is":
        Du(t, "is", a);
        break;
      case "innerText":
      case "textContent":
        return;
      default:
        if (!(2 < l.length) || l[0] !== "o" && l[0] !== "O" || l[1] !== "n" && l[1] !== "N")
          l = g0.get(l) || l, Du(t, l, a);
        else return;
    }
    St = !0;
  }
  function vf(t, e, l, a, n, u) {
    switch (l) {
      case "style":
        Ro(t, a, u);
        return;
      case "dangerouslySetInnerHTML":
        if (a != null) {
          if (typeof a != "object" || !("__html" in a))
            throw Error(o(61));
          if (l = a.__html, l != null) {
            if (n.children != null) throw Error(o(60));
            u?.__html !== l && (t.innerHTML = l);
          }
        }
        break;
      case "children":
        if (typeof a == "string") Ua(t, a);
        else if (typeof a == "number" || typeof a == "bigint")
          Ua(t, "" + a);
        else return;
        break;
      case "onScroll":
        a != null && ht("scroll", t);
        return;
      case "onScrollEnd":
        a != null && ht("scrollend", t);
        return;
      case "onClick":
        a != null && (t.onclick = tl);
        return;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "innerHTML":
      case "ref":
        return;
      case "innerText":
      case "textContent":
        return;
      default:
        if (!_o.hasOwnProperty(l))
          t: {
            if (l[0] === "o" && l[1] === "n" && (n = l.endsWith("Capture"), u = l.slice(2, n ? l.length - 7 : void 0), e = t[ye] || null, e = e != null ? e[l] : null, typeof e == "function" && t.removeEventListener(u, e, n), typeof a == "function")) {
              typeof e != "function" && e !== null && (l in t ? t[l] = null : t.hasAttribute(l) && t.removeAttribute(l)), t.addEventListener(u, a, n);
              break t;
            }
            St = !0, l in t ? t[l] = a : a === !0 ? t.setAttribute(l, "") : Du(t, l, a);
          }
        return;
    }
    St = !0;
  }
  function ce(t, e, l) {
    switch (e) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "img":
        ht("error", t), ht("load", t);
        var a = !1, n = !1, u;
        for (u in l)
          if (l.hasOwnProperty(u)) {
            var i = l[u];
            if (i != null)
              switch (u) {
                case "src":
                  a = !0;
                  break;
                case "srcSet":
                  n = !0;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  throw Error(o(137, e));
                default:
                  jt(t, e, u, i, l, null);
              }
          }
        n && jt(t, e, "srcSet", l.srcSet, l, null), a && jt(t, e, "src", l.src, l, null);
        return;
      case "input":
        ht("invalid", t);
        var f = u = i = n = null, m = null, x = null;
        for (a in l)
          if (l.hasOwnProperty(a)) {
            var j = l[a];
            if (j != null)
              switch (a) {
                case "name":
                  n = j;
                  break;
                case "type":
                  i = j;
                  break;
                case "checked":
                  m = j;
                  break;
                case "defaultChecked":
                  x = j;
                  break;
                case "value":
                  u = j;
                  break;
                case "defaultValue":
                  f = j;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  if (j != null)
                    throw Error(o(137, e));
                  break;
                default:
                  jt(t, e, a, j, l, null);
              }
          }
        Ao(
          t,
          u,
          f,
          m,
          x,
          i,
          n,
          !1
        );
        return;
      case "select":
        ht("invalid", t), a = i = u = null;
        for (n in l)
          if (l.hasOwnProperty(n) && (f = l[n], f != null))
            switch (n) {
              case "value":
                u = f;
                break;
              case "defaultValue":
                i = f;
                break;
              case "multiple":
                a = f;
              default:
                jt(t, e, n, f, l, null);
            }
        e = u, l = i, t.multiple = !!a, e != null ? Da(t, !!a, e, !1) : l != null && Da(t, !!a, l, !0);
        return;
      case "textarea":
        ht("invalid", t), u = n = a = null;
        for (i in l)
          if (l.hasOwnProperty(i) && (f = l[i], f != null))
            switch (i) {
              case "value":
                a = f;
                break;
              case "defaultValue":
                n = f;
                break;
              case "children":
                u = f;
                break;
              case "dangerouslySetInnerHTML":
                if (f != null) throw Error(o(91));
                break;
              default:
                jt(t, e, i, f, l, null);
            }
        Mo(t, a, n, u);
        return;
      case "option":
        for (m in l)
          l.hasOwnProperty(m) && (a = l[m], a != null) && (m === "selected" ? t.selected = a && typeof a != "function" && typeof a != "symbol" : jt(t, e, m, a, l, null));
        return;
      case "dialog":
        ht("beforetoggle", t), ht("toggle", t), ht("cancel", t), ht("close", t);
        break;
      case "iframe":
      case "object":
        ht("load", t);
        break;
      case "video":
      case "audio":
        for (a = 0; a < cu.length; a++)
          ht(cu[a], t);
        break;
      case "image":
        ht("error", t), ht("load", t);
        break;
      case "details":
        ht("toggle", t);
        break;
      case "embed":
      case "source":
      case "link":
        ht("error", t), ht("load", t);
      case "area":
      case "base":
      case "br":
      case "col":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "track":
      case "wbr":
      case "menuitem":
        for (x in l)
          if (l.hasOwnProperty(x) && (a = l[x], a != null))
            switch (x) {
              case "children":
              case "dangerouslySetInnerHTML":
                throw Error(o(137, e));
              default:
                jt(t, e, x, a, l, null);
            }
        return;
      default:
        if (gc(e)) {
          for (j in l)
            l.hasOwnProperty(j) && (a = l[j], a !== void 0 && vf(
              t,
              e,
              j,
              a,
              l,
              void 0
            ));
          return;
        }
    }
    for (f in l)
      l.hasOwnProperty(f) && (a = l[f], a != null && jt(t, e, f, a, l, null));
  }
  var Py = {};
  function tv(t, e, l, a) {
    switch (e) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "input":
        var n = null, u = null, i = null, f = null, m = null, x = null, j = null;
        for (T in l) {
          var C = l[T];
          if (l.hasOwnProperty(T) && C != null)
            switch (T) {
              case "checked":
                break;
              case "value":
                break;
              case "defaultValue":
                m = C;
              default:
                a.hasOwnProperty(T) || jt(t, e, T, null, a, C);
            }
        }
        for (var g in a) {
          var T = a[g];
          if (C = l[g], a.hasOwnProperty(g) && (T != null || C != null))
            switch (g) {
              case "type":
                T !== C && (St = !0), u = T;
                break;
              case "name":
                T !== C && (St = !0), n = T;
                break;
              case "checked":
                T !== C && (St = !0), x = T;
                break;
              case "defaultChecked":
                T !== C && (St = !0), j = T;
                break;
              case "value":
                T !== C && (St = !0), i = T;
                break;
              case "defaultValue":
                T !== C && (St = !0), f = T;
                break;
              case "children":
              case "dangerouslySetInnerHTML":
                if (T != null)
                  throw Error(o(137, e));
                break;
              default:
                T !== C && jt(
                  t,
                  e,
                  g,
                  T,
                  a,
                  C
                );
            }
        }
        yc(
          t,
          i,
          f,
          m,
          x,
          j,
          u,
          n
        );
        return;
      case "select":
        T = i = f = g = null;
        for (u in l)
          if (m = l[u], l.hasOwnProperty(u) && m != null)
            switch (u) {
              case "value":
                break;
              case "multiple":
                T = m;
              default:
                a.hasOwnProperty(u) || jt(
                  t,
                  e,
                  u,
                  null,
                  a,
                  m
                );
            }
        for (n in a)
          if (u = a[n], m = l[n], a.hasOwnProperty(n) && (u != null || m != null))
            switch (n) {
              case "value":
                u !== m && (St = !0), g = u;
                break;
              case "defaultValue":
                u !== m && (St = !0), f = u;
                break;
              case "multiple":
                u !== m && (St = !0), i = u;
              default:
                u !== m && jt(
                  t,
                  e,
                  n,
                  u,
                  a,
                  m
                );
            }
        e = f, l = i, a = T, g != null ? Da(t, !!l, g, !1) : !!a != !!l && (e != null ? Da(t, !!l, e, !0) : Da(t, !!l, l ? [] : "", !1));
        return;
      case "textarea":
        T = g = null;
        for (f in l)
          if (n = l[f], l.hasOwnProperty(f) && n != null && !a.hasOwnProperty(f))
            switch (f) {
              case "value":
                break;
              case "children":
                break;
              default:
                jt(t, e, f, null, a, n);
            }
        for (i in a)
          if (n = a[i], u = l[i], a.hasOwnProperty(i) && (n != null || u != null))
            switch (i) {
              case "value":
                n !== u && (St = !0), g = n;
                break;
              case "defaultValue":
                n !== u && (St = !0), T = n;
                break;
              case "children":
                break;
              case "dangerouslySetInnerHTML":
                if (n != null) throw Error(o(91));
                break;
              default:
                n !== u && jt(t, e, i, n, a, u);
            }
        Oo(t, g, T);
        return;
      case "option":
        for (var L in l)
          g = l[L], l.hasOwnProperty(L) && g != null && !a.hasOwnProperty(L) && (L === "selected" ? t.selected = !1 : jt(
            t,
            e,
            L,
            null,
            a,
            g
          ));
        for (m in a)
          g = a[m], T = l[m], a.hasOwnProperty(m) && g !== T && (g != null || T != null) && (m === "selected" ? (g !== T && (St = !0), t.selected = g && typeof g != "function" && typeof g != "symbol") : jt(
            t,
            e,
            m,
            g,
            a,
            T
          ));
        return;
      case "img":
      case "link":
      case "area":
      case "base":
      case "br":
      case "col":
      case "embed":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "source":
      case "track":
      case "wbr":
      case "menuitem":
        for (var $ in l)
          g = l[$], l.hasOwnProperty($) && g != null && !a.hasOwnProperty($) && jt(t, e, $, null, a, g);
        for (x in a)
          if (g = a[x], T = l[x], a.hasOwnProperty(x) && g !== T && (g != null || T != null))
            switch (x) {
              case "children":
              case "dangerouslySetInnerHTML":
                if (g != null)
                  throw Error(o(137, e));
                break;
              default:
                jt(
                  t,
                  e,
                  x,
                  g,
                  a,
                  T
                );
            }
        return;
      default:
        if (gc(e)) {
          for (var ct in l)
            g = l[ct], l.hasOwnProperty(ct) && g !== void 0 && !a.hasOwnProperty(ct) && vf(
              t,
              e,
              ct,
              void 0,
              a,
              g
            );
          for (j in a)
            g = a[j], T = l[j], !a.hasOwnProperty(j) || g === T || g === void 0 && T === void 0 || vf(
              t,
              e,
              j,
              g,
              a,
              T
            );
          return;
        }
    }
    for (var b in l)
      g = l[b], l.hasOwnProperty(b) && g != null && !a.hasOwnProperty(b) && jt(t, e, b, null, a, g);
    for (C in a)
      g = a[C], T = l[C], !a.hasOwnProperty(C) || g === T || g == null && T == null || jt(t, e, C, g, a, T);
  }
  function qm(t) {
    switch (t) {
      case "css":
      case "script":
      case "font":
      case "img":
      case "image":
      case "input":
      case "link":
        return !0;
      default:
        return !1;
    }
  }
  function ev() {
    if (typeof performance.getEntriesByType == "function") {
      for (var t = 0, e = 0, l = performance.getEntriesByType("resource"), a = 0; a < l.length; a++) {
        var n = l[a], u = n.transferSize, i = n.initiatorType, f = n.duration;
        if (u && f && qm(i)) {
          for (i = 0, f = n.responseEnd, a += 1; a < l.length; a++) {
            var m = l[a], x = m.startTime;
            if (x > f) break;
            var j = m.transferSize, C = m.initiatorType;
            j && qm(C) && (m = m.responseEnd, i += j * (m < f ? 1 : (f - x) / (m - x)));
          }
          if (--a, e += 8 * (u + i) / (n.duration / 1e3), t++, 10 < t) break;
        }
      }
      if (0 < t) return e / t / 1e6;
    }
    return navigator.connection && (t = navigator.connection.downlink, typeof t == "number") ? t : 5;
  }
  var gf = null, pf = null;
  function fu(t) {
    return t.nodeType === 9 ? t : t.ownerDocument;
  }
  function Ym(t) {
    switch (t) {
      case "http://www.w3.org/2000/svg":
        return 1;
      case "http://www.w3.org/1998/Math/MathML":
        return 2;
      default:
        return 0;
    }
  }
  function Lm(t, e) {
    if (t === 0)
      switch (e) {
        case "svg":
          return 1;
        case "math":
          return 2;
        default:
          return 0;
      }
    return t === 1 && e === "foreignObject" ? 0 : t;
  }
  function Xm(t, e, l, a) {
    return l = fu(
      l
    ).createElement(t), l[le] = a, l[ye] = e, ce(l, t, e), Wt(l), l;
  }
  function bf(t, e) {
    return t === "textarea" || t === "noscript" || typeof e.children == "string" || typeof e.children == "number" || typeof e.children == "bigint" || typeof e.dangerouslySetInnerHTML == "object" && e.dangerouslySetInnerHTML !== null && e.dangerouslySetInnerHTML.__html != null;
  }
  var xf = null;
  function lv() {
    var t = window.event;
    return t && t.type === "popstate" ? t === xf ? !1 : (xf = t, !0) : (xf = null, !1);
  }
  var Sf = typeof setTimeout == "function" ? setTimeout : void 0, av = typeof clearTimeout == "function" ? clearTimeout : void 0, Gm = typeof Promise == "function" ? Promise : void 0, Qm = typeof requestAnimationFrame == "function" ? requestAnimationFrame : Sf, nv = typeof queueMicrotask == "function" ? queueMicrotask : typeof Gm < "u" ? function(t) {
    return Gm.resolve(null).then(t).catch(uv);
  } : Sf;
  function uv(t) {
    setTimeout(function() {
      throw t;
    });
  }
  function Wl(t) {
    return t === "head";
  }
  function Vm(t, e) {
    var l = e, a = 0;
    do {
      var n = l.nextSibling;
      if (t.removeChild(l), n && n.nodeType === 8)
        if (l = n.data, l === "/$" || l === "/&") {
          if (a === 0) {
            t.removeChild(n), pn(e);
            return;
          }
          a--;
        } else if (l === "$" || l === "$?" || l === "$~" || l === "$!" || l === "&")
          a++;
        else if (l === "html")
          Of(
            t.ownerDocument.documentElement
          );
        else if (l === "head") {
          l = t.ownerDocument.head, Of(l);
          for (var u = l.firstChild; u; ) {
            var i = u.nextSibling, f = u.nodeName;
            u[zn] || f === "SCRIPT" || f === "STYLE" || f === "LINK" && u.rel.toLowerCase() === "stylesheet" || l.removeChild(u), u = i;
          }
        } else
          l === "body" && Of(t.ownerDocument.body);
      l = n;
    } while (l);
    pn(e);
  }
  function Zm(t, e) {
    var l = t;
    t = 0;
    do {
      var a = l.nextSibling;
      if (l.nodeType === 1 ? e ? (l._stashedDisplay = l.style.display, l.style.display = "none") : (l.style.display = l._stashedDisplay || "", l.getAttribute("style") === "" && l.removeAttribute("style")) : l.nodeType === 3 && (e ? (l._stashedText = l.nodeValue, l.nodeValue = "") : l.nodeValue = l._stashedText || ""), a && a.nodeType === 8)
        if (l = a.data, l === "/$") {
          if (t === 0) break;
          t--;
        } else
          l !== "$" && l !== "$?" && l !== "$~" && l !== "$!" || t++;
      l = a;
    } while (l);
  }
  function Km(t, e, l) {
    if (e = CSS.escape(e) !== e ? "r-" + btoa(e).replace(/=/g, "") : e, t.style.viewTransitionName = e, l != null && (t.style.viewTransitionClass = l), l = getComputedStyle(t), l.display === "inline") {
      if (e = t.getClientRects(), e.length === 1) var a = 1;
      else
        for (var n = a = 0; n < e.length; n++) {
          var u = e[n];
          0 < u.width && 0 < u.height && a++;
        }
      a === 1 && (t = t.style, t.display = e.length === 1 ? "inline-block" : "block", t.marginTop = "-" + l.paddingTop, t.marginBottom = "-" + l.paddingBottom);
    }
  }
  function km(t, e) {
    t = t.style, e = e.style;
    var l = e != null ? e.hasOwnProperty("viewTransitionName") ? e.viewTransitionName : e.hasOwnProperty("view-transition-name") ? e["view-transition-name"] : null : null;
    t.viewTransitionName = l == null || typeof l == "boolean" ? "" : ("" + l).trim(), l = e != null ? e.hasOwnProperty("viewTransitionClass") ? e.viewTransitionClass : e.hasOwnProperty("view-transition-class") ? e["view-transition-class"] : null : null, t.viewTransitionClass = l == null || typeof l == "boolean" ? "" : ("" + l).trim(), t.display === "inline-block" && (e == null ? t.display = t.margin = "" : (l = e.display, t.display = l == null || typeof l == "boolean" ? "" : l, l = e.margin, l != null ? t.margin = l : (l = e.hasOwnProperty("marginTop") ? e.marginTop : e["margin-top"], t.marginTop = l == null || typeof l == "boolean" ? "" : l, e = e.hasOwnProperty("marginBottom") ? e.marginBottom : e["margin-bottom"], t.marginBottom = e == null || typeof e == "boolean" ? "" : e)));
  }
  function iv(t, e, l) {
    return l = l.ownerDocument.defaultView, {
      rect: t,
      abs: e.position === "absolute" || e.position === "fixed",
      clip: e.clipPath !== "none" || e.overflow !== "visible" || e.filter !== "none" || e.mask !== "none" || e.mask !== "none" || e.borderRadius !== "0px",
      view: 0 <= t.bottom && 0 <= t.right && t.top <= l.innerHeight && t.left <= l.innerWidth
    };
  }
  function _f(t) {
    var e = t.getBoundingClientRect(), l = getComputedStyle(t);
    return iv(e, l, t);
  }
  function cv(t) {
    return t.documentElement.clientHeight;
  }
  function sv(t) {
    this.addEventListener("load", t), this.addEventListener("error", t);
  }
  function fv(t, e, l, a, n, u, i, f, m) {
    var x = e.nodeType === 9 ? e : e.ownerDocument;
    try {
      var j = x.startViewTransition({
        update: function() {
          var g = x.defaultView, T = g.navigation && g.navigation.transition, L = x.fonts.status;
          a();
          var $ = [];
          if (L === "loaded" && (cv(x), x.fonts.status === "loading" && $.push(x.fonts.ready)), L = $.length, t !== null)
            for (var ct = t.suspenseyImages, b = 0, v = 0; v < ct.length; v++) {
              var S = ct[v];
              if (!S.complete) {
                var O = S.getBoundingClientRect();
                if (0 < O.bottom && 0 < O.right && O.top < g.innerHeight && O.left < g.innerWidth) {
                  if (b += hh(S), b > Vi) {
                    $.length = L;
                    break;
                  }
                  S = new Promise(
                    sv.bind(S)
                  ), $.push(S);
                }
              }
            }
          if (0 < $.length)
            return g = Promise.race([
              Promise.all($),
              new Promise(function(Z) {
                return setTimeout(Z, 500);
              })
            ]).then(n, n), (T ? Promise.allSettled([T.finished, g]) : g).then(u, u);
          if (n(), T)
            return T.finished.then(
              u,
              u
            );
          u();
        },
        types: l
      });
      x.__reactViewTransition = j;
      var C = [];
      return j.ready.then(
        function() {
          for (var g = x.documentElement.getAnimations({
            subtree: !0
          }), T = 0; T < g.length; T++) {
            var L = g[T], $ = L.effect, ct = $.pseudoElement;
            if (ct != null && ct.startsWith("::view-transition")) {
              C.push(L), L = $.getKeyframes();
              for (var b = ct = void 0, v = !0, S = 0; S < L.length; S++) {
                var O = L[S], Z = O.width;
                if (ct === void 0) ct = Z;
                else if (ct !== Z) {
                  v = !1;
                  break;
                }
                if (Z = O.height, b === void 0) b = Z;
                else if (b !== Z) {
                  v = !1;
                  break;
                }
                delete O.width, delete O.height, O.transform === "none" && delete O.transform;
              }
              v && ct !== void 0 && b !== void 0 && ($.setKeyframes(L), v = getComputedStyle(
                $.target,
                $.pseudoElement
              ), v.width !== ct || v.height !== b) && (v = L[0], v.width = ct, v.height = b, v = L[L.length - 1], v.width = ct, v.height = b, $.setKeyframes(L));
            }
          }
          i();
        },
        function(g) {
          x.__reactViewTransition === j && (x.__reactViewTransition = null);
          try {
            typeof g == "object" && g !== null && g.name === "InvalidStateError" && (g.message === "View transition was skipped because document visibility state is hidden." || g.message === "Skipping view transition because document visibility state has become hidden." || g.message === "Skipping view transition because viewport size changed." || g.message === "Transition was aborted because of invalid state") && (g = null), g !== null && m(g);
          } finally {
            a(), n(), i();
          }
        }
      ), j.finished.finally(function() {
        for (var g = 0; g < C.length; g++)
          C[g].cancel();
        x.__reactViewTransition === j && (x.__reactViewTransition = null), f();
      }), j;
    } catch {
      return a(), n(), i(), null;
    }
  }
  function ja(t, e) {
    this._scope = document.documentElement, this._selector = "::view-transition-" + t + "(" + e + ")";
  }
  ja.prototype.animate = function(t, e) {
    return e = typeof e == "number" ? { duration: e } : V({}, e), e.pseudoElement = this._selector, this._scope.animate(t, e);
  }, ja.prototype.getAnimations = function() {
    for (var t = this._scope, e = this._selector, l = t.getAnimations({ subtree: !0 }), a = [], n = 0; n < l.length; n++) {
      var u = l[n].effect;
      u !== null && u.target === t && u.pseudoElement === e && a.push(l[n]);
    }
    return a;
  }, ja.prototype.getComputedStyle = function() {
    return getComputedStyle(this._scope, this._selector);
  };
  function Jm(t) {
    return {
      name: t,
      group: new ja("group", t),
      imagePair: new ja("image-pair", t),
      old: new ja("old", t),
      new: new ja("new", t)
    };
  }
  function Re(t) {
    this._fragmentFiber = t, this._observers = this._eventListeners = null;
  }
  Re.prototype.addEventListener = function(t, e, l) {
    var a = null, n = null;
    if (!(l != null && typeof l != "boolean" && (a = l.signal || null, a !== null && a.aborted))) {
      this._eventListeners === null && (this._eventListeners = []);
      var u = this._eventListeners;
      if (Fm(u, t, e, l) === -1) {
        var i = this, f = e;
        l != null && typeof l != "boolean" && l.once === !0 && (f = function(m) {
          i.removeEventListener(
            t,
            e,
            l
          ), typeof e == "function" ? e.call(this, m) : e.handleEvent(m);
        }), a !== null && (n = i.removeEventListener.bind(
          i,
          t,
          e,
          l
        ), a.addEventListener("abort", n, { once: !0 }), n = a.removeEventListener.bind(a, "abort", n)), a = dn(l), u.push({
          type: t,
          listener: e,
          optionsOrUseCapture: l,
          attachedListener: f,
          cleanup: n
        }), N(
          this._fragmentFiber.child,
          !1,
          ov,
          t,
          f,
          a
        );
      }
      this._eventListeners = u;
    }
  };
  function ov(t, e, l, a) {
    return Q(t).addEventListener(
      e,
      l,
      a
    ), !1;
  }
  Re.prototype.removeEventListener = function(t, e, l) {
    var a = this._eventListeners;
    if (a !== null && (e = Fm(
      a,
      t,
      e,
      l
    ), e !== -1)) {
      var n = a[e];
      l = n.attachedListener;
      var u = n.cleanup;
      n = dn(n.optionsOrUseCapture), N(
        this._fragmentFiber.child,
        !1,
        rv,
        t,
        l,
        n
      ), a.splice(e, 1), u !== null && u();
    }
  };
  function rv(t, e, l, a) {
    return Q(t).removeEventListener(
      e,
      l,
      a
    ), !1;
  }
  function dn(t) {
    return t != null && typeof t != "boolean" && (t.once === !0 || t.signal instanceof AbortSignal) ? { capture: t.capture, passive: t.passive } : t;
  }
  function $m(t) {
    return t == null ? "c=0" : typeof t == "boolean" ? "c=" + (t ? "1" : "0") : "c=" + (t.capture ? "1" : "0");
  }
  function Fm(t, e, l, a) {
    if (t.length === 0) return -1;
    a = $m(a);
    for (var n = 0; n < t.length; n++) {
      var u = t[n];
      if (u.type === e && u.listener === l && $m(u.optionsOrUseCapture) === a)
        return n;
    }
    return -1;
  }
  Re.prototype.dispatchEvent = function(t) {
    var e = w(
      this._fragmentFiber
    );
    if (e === null) return !0;
    e = Q(e);
    var l = this._eventListeners;
    if (l !== null && 0 < l.length || !t.bubbles) {
      var a = e.nodeType === 9 ? e.createComment("") : document.createTextNode("");
      if (l)
        for (var n = 0; n < l.length; n++) {
          var u = l[n];
          a.addEventListener(
            u.type,
            u.attachedListener,
            dn(u.optionsOrUseCapture)
          );
        }
      if (e.appendChild(a), t = a.dispatchEvent(t), l)
        for (n = 0; n < l.length; n++)
          u = l[n], a.removeEventListener(
            u.type,
            u.attachedListener,
            dn(u.optionsOrUseCapture)
          );
      return e.removeChild(a), t;
    }
    return e.dispatchEvent(t);
  }, Re.prototype.focus = function(t) {
    N(
      this._fragmentFiber.child,
      !0,
      Wm,
      t,
      void 0,
      void 0
    );
  };
  function Wm(t, e) {
    return t.tag === 6 ? !1 : (t = Q(t), Nv(t, e));
  }
  Re.prototype.focusLast = function(t) {
    var e = [];
    N(
      this._fragmentFiber.child,
      !0,
      Nf,
      e,
      void 0,
      void 0
    );
    for (var l = e.length - 1; 0 <= l && !Wm(e[l], t); l--) ;
  };
  function Nf(t, e) {
    return e.push(t), !1;
  }
  Re.prototype.blur = function() {
    var t = w(
      this._fragmentFiber
    );
    t !== null && (t = Q(t), t = fu(t).activeElement, t !== null && N(
      this._fragmentFiber.child,
      !1,
      dv,
      t,
      void 0,
      void 0
    ));
  };
  function dv(t, e) {
    return t.tag === 6 ? !1 : (t = Q(t), t === e || t.contains(e) ? (e.blur(), !0) : !1);
  }
  Re.prototype.observeUsing = function(t) {
    this._observers === null && (this._observers = /* @__PURE__ */ new Set()), this._observers.add(t), N(
      this._fragmentFiber.child,
      !1,
      mv,
      t,
      void 0,
      void 0
    );
  };
  function mv(t, e) {
    return t.tag === 6 || (t = Q(t), e.observe(t)), !1;
  }
  Re.prototype.unobserveUsing = function(t) {
    var e = this._observers;
    if (e !== null && e.has(t)) {
      e.delete(t), N(
        this._fragmentFiber.child,
        !1,
        hv,
        t,
        void 0,
        void 0
      );
      for (var l = e = 0; l < Ie.length; l++) {
        var a = Ie[l];
        a.fragmentInstance === this && a.observer === t ? t.unobserve(a.instance) : Ie[e++] = a;
      }
      Ie.length = e;
    }
  };
  function hv(t, e) {
    return t.tag === 6 || (t = Q(t), e.unobserve(t)), !1;
  }
  var Ie = [], Tf = !1;
  function yv(t, e, l) {
    Ie.push({
      fragmentInstance: t,
      observer: e,
      instance: l
    }), Tf || (Tf = !0, Tv(function() {
      Tf = !1;
      var a = Ie;
      Ie = [];
      for (var n = 0; n < a.length; n++) {
        var u = a[n];
        u.observer.unobserve(u.instance);
      }
    }));
  }
  Re.prototype.getClientRects = function() {
    var t = [];
    return N(
      this._fragmentFiber.child,
      !1,
      vv,
      t,
      void 0,
      void 0
    ), t;
  };
  function vv(t, e) {
    if (t.tag === 6) {
      t = t.stateNode;
      var l = t.ownerDocument.createRange();
      l.selectNodeContents(t), e.push.apply(e, l.getClientRects());
    } else
      t = Q(t), e.push.apply(e, t.getClientRects());
    return !1;
  }
  Re.prototype.getRootNode = function(t) {
    var e = w(
      this._fragmentFiber
    );
    return e === null ? this : Q(e).getRootNode(t);
  }, Re.prototype.compareDocumentPosition = function(t) {
    var e = w(
      this._fragmentFiber
    );
    if (e === null) return Node.DOCUMENT_POSITION_DISCONNECTED;
    var l = [];
    N(
      this._fragmentFiber.child,
      !1,
      Nf,
      l,
      void 0,
      void 0
    );
    var a = Q(e);
    if (l.length === 0) {
      if (l = a, Y(this._fragmentFiber)) {
        t: {
          for (e = this._fragmentFiber.return; e !== null; ) {
            if (e.tag === 4) {
              e = e.stateNode.containerInfo;
              break t;
            }
            if (e.tag === 3 || e.tag === 5 || e.tag === 27)
              break;
            e = e.return;
          }
          e = null;
        }
        e != null && (l = e);
      }
      e = this._fragmentFiber;
      var n = a = l.compareDocumentPosition(t);
      return l === t ? n = Node.DOCUMENT_POSITION_CONTAINS : a & Node.DOCUMENT_POSITION_CONTAINED_BY && (l = F(e)[1], l === null ? n = Node.DOCUMENT_POSITION_PRECEDING : (t = Q(l).compareDocumentPosition(
        t
      ), n = t === 0 || t & Node.DOCUMENT_POSITION_FOLLOWING ? Node.DOCUMENT_POSITION_FOLLOWING : Node.DOCUMENT_POSITION_PRECEDING)), n |= Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC;
    }
    e = Q(l[0]), n = Q(l[l.length - 1]);
    var u = Y(this._fragmentFiber) ? e.parentElement : a;
    if (u == null)
      return Node.DOCUMENT_POSITION_DISCONNECTED;
    a = u.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_CONTAINED_BY, u = u.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_CONTAINED_BY;
    var i = e.compareDocumentPosition(t), f = n.compareDocumentPosition(t), m = i & Node.DOCUMENT_POSITION_CONTAINED_BY || f & Node.DOCUMENT_POSITION_CONTAINED_BY;
    return f = a && u && i & Node.DOCUMENT_POSITION_FOLLOWING && f & Node.DOCUMENT_POSITION_PRECEDING, e = a && e === t || u && n === t || m || f ? Node.DOCUMENT_POSITION_CONTAINED_BY : !a && e === t || !u && n === t ? Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC : i, e & Node.DOCUMENT_POSITION_DISCONNECTED || e & Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC || gv(
      e,
      this._fragmentFiber,
      l[0],
      l[l.length - 1],
      t
    ) ? e : Node.DOCUMENT_POSITION_IMPLEMENTATION_SPECIFIC;
  };
  function gv(t, e, l, a, n) {
    var u = ua(n);
    if (t & Node.DOCUMENT_POSITION_CONTAINED_BY) {
      if (l = !!u)
        t: {
          for (; u !== null; ) {
            if (u.tag === 7 && (u === e || u.alternate === e)) {
              l = !0;
              break t;
            }
            u = u.return;
          }
          l = !1;
        }
      return l;
    }
    if (t & Node.DOCUMENT_POSITION_CONTAINS) {
      if (u === null)
        return u = n.ownerDocument, n === u || n === u.documentElement || n === u.body;
      t: {
        for (u = e, e = w(e); u !== null; ) {
          if (!(u.tag !== 5 && u.tag !== 3 && u.tag !== 27 || u !== e && u.alternate !== e)) {
            u = !0;
            break t;
          }
          u = u.return;
        }
        u = !1;
      }
      return u;
    }
    return t & Node.DOCUMENT_POSITION_PRECEDING ? ((e = !!u) && !(e = u === l) && (e = dt(
      l,
      u,
      ft
    ), e === null ? e = !1 : (N(
      e,
      !0,
      wt,
      u,
      l
    ), u = rt, rt = null, e = u !== null)), e) : t & Node.DOCUMENT_POSITION_FOLLOWING ? ((e = !!u) && !(e = u === a) && (e = dt(
      a,
      u,
      ft
    ), e === null ? e = !1 : (N(
      e,
      !0,
      bt,
      u,
      a
    ), u = rt, nt = rt = null, e = u !== null)), e) : !1;
  }
  function Im(t, e) {
    var l = t.ownerDocument.createRange();
    l.selectNodeContents(t), t = l.getBoundingClientRect(), window.scrollTo(
      window.scrollX + t.left,
      e ? window.scrollY + t.top : window.scrollY + t.bottom - window.innerHeight
    );
  }
  Re.prototype.scrollIntoView = function(t) {
    if (typeof t == "object") throw Error(o(566));
    var e = [];
    N(
      this._fragmentFiber.child,
      !1,
      Nf,
      e,
      void 0,
      void 0
    );
    var l = t !== !1;
    if (e.length === 0) {
      var a = F(
        this._fragmentFiber
      );
      if (a = l ? a[1] || a[0] || w(this._fragmentFiber) : a[0] || a[1], a === null) return;
      if (a.tag === 6) {
        t = Q(a), Im(t, l);
        return;
      }
      if (a = Q(a), a.nodeType !== 9) {
        if (a.nodeType === 11) {
          l = "host" in a ? a.host : null, l !== null && l.scrollIntoView(t);
          return;
        }
        a.scrollIntoView(t);
      }
    }
    for (a = l ? e.length - 1 : 0; a !== (l ? -1 : e.length); ) {
      var n = e[a];
      n.tag === 6 ? (n = Q(n), Im(n, l)) : Q(n).scrollIntoView(t), a += l ? -1 : 1;
    }
  };
  function pv(t, e) {
    return t = Q(t), Pm(t, e), !1;
  }
  function Pm(t, e) {
    t.reactFragments == null && (t.reactFragments = /* @__PURE__ */ new Set()), t.reactFragments.add(e);
  }
  function th(t, e) {
    var l = e._eventListeners;
    if (l !== null)
      for (var a = 0; a < l.length; a++) {
        var n = l[a];
        t.addEventListener(
          n.type,
          n.attachedListener,
          dn(n.optionsOrUseCapture)
        );
      }
    t.nodeType !== 3 && (l = e._observers, l !== null && l.forEach(function(u) {
      for (var i = 0, f = 0; f < Ie.length; f++) {
        var m = Ie[f];
        (m.fragmentInstance !== e || m.observer !== u || m.instance !== t) && (Ie[i++] = m);
      }
      Ie.length = i, u.observe(t);
    }), Pm(t, e));
  }
  function bv(t, e) {
    var l = e._eventListeners;
    if (l !== null)
      for (var a = 0; a < l.length; a++) {
        var n = l[a];
        t.removeEventListener(
          n.type,
          n.attachedListener,
          dn(n.optionsOrUseCapture)
        );
      }
    t.nodeType !== 3 && (l = e._observers, l !== null && l.forEach(function(u) {
      typeof u.rootMargin == "string" ? yv(
        e,
        u,
        t
      ) : u.unobserve(t);
    }), t.reactFragments != null && t.reactFragments.delete(e));
  }
  function Ef(t) {
    var e = t.firstChild;
    for (e && e.nodeType === 10 && (e = e.nextSibling); e; ) {
      var l = e;
      switch (e = e.nextSibling, l.nodeName) {
        case "HTML":
        case "HEAD":
        case "BODY":
          Ef(l), Ru(l);
          continue;
        case "SCRIPT":
        case "STYLE":
          continue;
        case "LINK":
          if (l.rel.toLowerCase() === "stylesheet") continue;
      }
      t.removeChild(l);
    }
  }
  function xv(t, e, l, a) {
    for (; t.nodeType === 1; ) {
      var n = l;
      if (t.nodeName.toLowerCase() !== e.toLowerCase()) {
        if (!a && (t.nodeName !== "INPUT" || t.type !== "hidden"))
          break;
      } else if (a) {
        if (!t[zn])
          switch (e) {
            case "meta":
              if (!t.hasAttribute("itemprop")) break;
              return t;
            case "link":
              if (u = t.getAttribute("rel"), u === "stylesheet" && t.hasAttribute("data-precedence"))
                break;
              if (u !== n.rel || t.getAttribute("href") !== (n.href == null || n.href === "" ? null : n.href) || t.getAttribute("crossorigin") !== (n.crossOrigin == null ? null : n.crossOrigin) || t.getAttribute("title") !== (n.title == null ? null : n.title))
                break;
              return t;
            case "style":
              if (t.hasAttribute("data-precedence")) break;
              return t;
            case "script":
              if (u = t.getAttribute("src"), (u !== (n.src == null ? null : n.src) || t.getAttribute("type") !== (n.type == null ? null : n.type) || t.getAttribute("crossorigin") !== (n.crossOrigin == null ? null : n.crossOrigin)) && u && t.hasAttribute("async") && !t.hasAttribute("itemprop"))
                break;
              return t;
            default:
              return t;
          }
      } else if (e === "input" && t.type === "hidden") {
        var u = n.name == null ? null : "" + n.name;
        if (n.type === "hidden" && t.getAttribute("name") === u)
          return t;
      } else return t;
      if (t = Qe(t.nextSibling), t === null) break;
    }
    return null;
  }
  function Sv(t, e, l) {
    if (e === "") return null;
    for (; t.nodeType !== 3; )
      if ((t.nodeType !== 1 || t.nodeName !== "INPUT" || t.type !== "hidden") && !l || (t = Qe(t.nextSibling), t === null)) return null;
    return t;
  }
  function eh(t, e) {
    for (; t.nodeType !== 8; )
      if ((t.nodeType !== 1 || t.nodeName !== "INPUT" || t.type !== "hidden") && !e || (t = Qe(t.nextSibling), t === null)) return null;
    return t;
  }
  function jf(t) {
    return t.data === "$?" || t.data === "$~";
  }
  function zf(t) {
    return t.data === "$!" || t.data === "$?" && t.ownerDocument.readyState !== "loading";
  }
  function _v(t, e) {
    var l = t.ownerDocument;
    if (t.data === "$~") t._reactRetry = e;
    else if (t.data !== "$?" || l.readyState !== "loading")
      e();
    else {
      var a = function() {
        e(), l.removeEventListener("DOMContentLoaded", a);
      };
      l.addEventListener("DOMContentLoaded", a), t._reactRetry = a;
    }
  }
  function Qe(t) {
    for (; t != null; t = t.nextSibling) {
      var e = t.nodeType;
      if (e === 1 || e === 3) break;
      if (e === 8) {
        if (e = t.data, e === "$" || e === "$!" || e === "$?" || e === "$~" || e === "&" || e === "F!" || e === "F")
          break;
        if (e === "/$" || e === "/&") return null;
      }
    }
    return t;
  }
  var Af = null;
  function lh(t) {
    t = t.nextSibling;
    for (var e = 0; t; ) {
      if (t.nodeType === 8) {
        var l = t.data;
        if (l === "/$" || l === "/&") {
          if (e === 0)
            return Qe(t.nextSibling);
          e--;
        } else
          l !== "$" && l !== "$!" && l !== "$?" && l !== "$~" && l !== "&" || e++;
      }
      t = t.nextSibling;
    }
    return null;
  }
  function ah(t) {
    t = t.previousSibling;
    for (var e = 0; t; ) {
      if (t.nodeType === 8) {
        var l = t.data;
        if (l === "$" || l === "$!" || l === "$?" || l === "$~" || l === "&") {
          if (e === 0) return t;
          e--;
        } else l !== "/$" && l !== "/&" || e++;
      }
      t = t.previousSibling;
    }
    return null;
  }
  function Nv(t, e) {
    function l() {
      a = !0;
    }
    if (t.ownerDocument.activeElement === t) return !0;
    var a = !1;
    try {
      t.ownerDocument.addEventListener("focus", l, !0), (t.focus || HTMLElement.prototype.focus).call(t, e);
    } finally {
      t.ownerDocument.removeEventListener("focus", l, !0);
    }
    return a;
  }
  function Tv(t) {
    Qm(function() {
      Qm(function(e) {
        return t(e);
      });
    });
  }
  function nh(t, e, l) {
    switch (e = fu(l), t) {
      case "html":
        if (t = e.documentElement, !t) throw Error(o(452));
        return t;
      case "head":
        if (t = e.head, !t) throw Error(o(453));
        return t;
      case "body":
        if (t = e.body, !t) throw Error(o(454));
        return t;
      default:
        throw Error(o(451));
    }
  }
  function uh(t, e, l) {
    for (var a in l) {
      var n = l[a];
      l.hasOwnProperty(a) && n != null && jt(t, e, a, null, Py, n);
    }
    l.dangerouslySetInnerHTML != null && (t.textContent = ""), t.onclick === tl && (t.onclick = null), Ru(t);
  }
  function Of(t) {
    for (var e = t.attributes; e.length; )
      t.removeAttributeNode(e[0]);
    Ru(t);
  }
  var Ve = /* @__PURE__ */ new Map(), ih = /* @__PURE__ */ new Set();
  function ou(t) {
    if (typeof t.getRootNode == "function") {
      var e = t.getRootNode();
      if (e.nodeType === 9 || e.nodeType === 11) return e;
    }
    return t.nodeType === 9 ? t : t.ownerDocument;
  }
  var zl = W.d;
  W.d = {
    f: Ev,
    r: jv,
    D: zv,
    C: Av,
    L: Ov,
    m: Mv,
    X: Rv,
    S: Cv,
    M: Dv
  };
  function Ev() {
    var t = zl.f(), e = wi();
    return t || e;
  }
  function jv(t) {
    var e = Ma(t);
    e !== null && e.tag === 5 && e.type === "form" ? sd(e) : zl.r(t);
  }
  var mn = typeof document > "u" ? null : document;
  function ch(t, e, l) {
    var a = mn;
    if (a && typeof e == "string" && e) {
      var n = He(e);
      n = 'link[rel="' + t + '"][href="' + n + '"]', typeof l == "string" && (n += '[crossorigin="' + l + '"]'), ih.has(n) || (ih.add(n), t = { rel: t, crossOrigin: l, href: e }, a.querySelector(n) === null && (e = a.createElement("link"), ce(e, "link", t), Wt(e), a.head.appendChild(e)));
    }
  }
  function zv(t) {
    zl.D(t), ch("dns-prefetch", t, null);
  }
  function Av(t, e) {
    zl.C(t, e), ch("preconnect", t, e);
  }
  function Ov(t, e, l) {
    zl.L(t, e, l);
    var a = mn;
    if (a && t && e) {
      var n = 'link[rel="preload"][as="' + He(e) + '"]';
      e === "image" && l && l.imageSrcSet ? (n += '[imagesrcset="' + He(
        l.imageSrcSet
      ) + '"]', typeof l.imageSizes == "string" && (n += '[imagesizes="' + He(
        l.imageSizes
      ) + '"]')) : n += '[href="' + He(t) + '"]';
      var u = n;
      switch (e) {
        case "style":
          u = hn(t);
          break;
        case "script":
          u = yn(t);
      }
      if (!(Ve.has(u) || (t = V(
        {
          rel: "preload",
          href: e === "image" && l && l.imageSrcSet ? void 0 : t,
          as: e
        },
        l
      ), Ve.set(u, t), a.querySelector(n) !== null || e === "style" && a.querySelector(ru(u)) || e === "script" && a.querySelector(du(u))))) {
        var i = a.createElement("link");
        ce(i, "link", t), e === "style" && (i[Cu] = !0, i.onload = i.onerror = function() {
          xo(i);
        }), Wt(i), a.head.appendChild(i);
      }
    }
  }
  function Mv(t, e) {
    zl.m(t, e);
    var l = mn;
    if (l && t) {
      var a = e && typeof e.as == "string" ? e.as : "script", n = 'link[rel="modulepreload"][as="' + He(a) + '"][href="' + He(t) + '"]', u = n;
      switch (a) {
        case "audioworklet":
        case "paintworklet":
        case "serviceworker":
        case "sharedworker":
        case "worker":
        case "script":
          u = yn(t);
      }
      if (!Ve.has(u) && (t = V({ rel: "modulepreload", href: t }, e), Ve.set(u, t), l.querySelector(n) === null)) {
        switch (a) {
          case "audioworklet":
          case "paintworklet":
          case "serviceworker":
          case "sharedworker":
          case "worker":
          case "script":
            if (l.querySelector(du(u)))
              return;
        }
        a = l.createElement("link"), ce(a, "link", t), Wt(a), l.head.appendChild(a);
      }
    }
  }
  function Cv(t, e, l) {
    zl.S(t, e, l);
    var a = mn;
    if (a && t) {
      var n = Ca(a).hoistableStyles, u = hn(t);
      e = e || "default";
      var i = n.get(u);
      if (!i) {
        var f = { loading: 0, preload: null };
        if (i = a.querySelector(
          ru(u)
        ))
          f.loading = 5;
        else {
          t = V(
            { rel: "stylesheet", href: t, "data-precedence": e },
            l
          ), (l = Ve.get(u)) && Mf(t, l);
          var m = i = a.createElement("link");
          Wt(m), ce(m, "link", t), m._p = new Promise(function(x, j) {
            m.onload = x, m.onerror = j;
          }), m.addEventListener("load", function() {
            f.loading |= 1;
          }), m.addEventListener("error", function() {
            f.loading |= 2;
          }), f.loading |= 4, Gi(i, e, a);
        }
        i = {
          type: "stylesheet",
          instance: i,
          count: 1,
          state: f
        }, n.set(u, i);
      }
    }
  }
  function Rv(t, e) {
    zl.X(t, e);
    var l = mn;
    if (l && t) {
      var a = Ca(l).hoistableScripts, n = yn(t), u = a.get(n);
      u || (u = l.querySelector(du(n)), u || (t = V({ src: t, async: !0 }, e), (e = Ve.get(n)) && Cf(t, e), u = l.createElement("script"), Wt(u), ce(u, "link", t), l.head.appendChild(u)), u = {
        type: "script",
        instance: u,
        count: 1,
        state: null
      }, a.set(n, u));
    }
  }
  function Dv(t, e) {
    zl.M(t, e);
    var l = mn;
    if (l && t) {
      var a = Ca(l).hoistableScripts, n = yn(t), u = a.get(n);
      u || (u = l.querySelector(du(n)), u || (t = V({ src: t, async: !0, type: "module" }, e), (e = Ve.get(n)) && Cf(t, e), u = l.createElement("script"), Wt(u), ce(u, "link", t), l.head.appendChild(u)), u = {
        type: "script",
        instance: u,
        count: 1,
        state: null
      }, a.set(n, u));
    }
  }
  function sh(t, e, l, a) {
    var n = (n = Al.current) ? ou(n) : null;
    if (!n) throw Error(o(446));
    switch (t) {
      case "meta":
      case "title":
        return null;
      case "style":
        return typeof l.precedence == "string" && typeof l.href == "string" ? (l = hn(l.href), e = Ca(
          n
        ).hoistableStyles, a = e.get(l), a || (a = {
          type: "style",
          instance: null,
          count: 0,
          state: null
        }, e.set(l, a)), a) : { type: "void", instance: null, count: 0, state: null };
      case "link":
        if (l.rel === "stylesheet" && typeof l.href == "string" && typeof l.precedence == "string") {
          t = hn(l.href);
          var u = Ca(
            n
          ).hoistableStyles, i = u.get(t);
          if (i || (n = n.ownerDocument || n, i = {
            type: "stylesheet",
            instance: null,
            count: 0,
            state: { loading: 0, preload: null }
          }, u.set(t, i), (u = n.querySelector(
            ru(t)
          )) ? u._p || (i.instance = u, i.state.loading = 5) : (u = Ve.get(t), u || (u = {
            rel: "preload",
            as: "style",
            href: l.href,
            crossOrigin: l.crossOrigin,
            integrity: l.integrity,
            media: l.media,
            hrefLang: l.hrefLang,
            referrerPolicy: l.referrerPolicy
          }, Ve.set(t, u)), Uv(
            n,
            t,
            u,
            i.state
          ))), e && a === null)
            throw Error(o(528, ""));
          return i;
        }
        if (e && a !== null)
          throw Error(o(529, ""));
        return null;
      case "script":
        return e = l.async, l = l.src, typeof l == "string" && e && typeof e != "function" && typeof e != "symbol" ? (l = yn(l), e = Ca(
          n
        ).hoistableScripts, a = e.get(l), a || (a = {
          type: "script",
          instance: null,
          count: 0,
          state: null
        }, e.set(l, a)), a) : { type: "void", instance: null, count: 0, state: null };
      default:
        throw Error(o(444, t));
    }
  }
  function hn(t) {
    return 'href="' + He(t) + '"';
  }
  function ru(t) {
    return 'link[rel="stylesheet"][' + t + "]";
  }
  function fh(t) {
    return V({}, t, {
      "data-precedence": t.precedence,
      precedence: null
    });
  }
  function Uv(t, e, l, a) {
    if (e = t.querySelector(
      'link[rel="preload"][as="style"][' + e + "]"
    )) {
      if (e[Cu] !== !0) {
        a.loading = 1;
        return;
      }
    } else
      e = t.createElement("link"), e[Cu] = !0, e.onload = e.onerror = xo.bind(null, e), ce(e, "link", l), Wt(e), t.head.appendChild(e);
    a.preload = e, e.addEventListener("load", function() {
      return a.loading |= 1;
    }), e.addEventListener("error", function() {
      return a.loading |= 2;
    });
  }
  function yn(t) {
    return '[src="' + He(t) + '"]';
  }
  function du(t) {
    return "script[async]" + t;
  }
  function oh(t, e, l) {
    if (e.count++, e.instance === null)
      switch (e.type) {
        case "style":
          var a = t.querySelector(
            'style[data-href~="' + He(l.href) + '"]'
          );
          if (a)
            return e.instance = a, Wt(a), a;
          var n = V({}, l, {
            "data-href": l.href,
            "data-precedence": l.precedence,
            href: null,
            precedence: null
          });
          return a = (t.ownerDocument || t).createElement(
            "style"
          ), Wt(a), ce(a, "style", n), Gi(a, l.precedence, t), e.instance = a;
        case "stylesheet":
          n = hn(l.href);
          var u = t.querySelector(
            ru(n)
          );
          if (u)
            return e.state.loading |= 4, e.instance = u, Wt(u), u;
          a = fh(l), (n = Ve.get(n)) && Mf(a, n), u = (t.ownerDocument || t).createElement("link"), Wt(u);
          var i = u;
          return i._p = new Promise(function(f, m) {
            i.onload = f, i.onerror = m;
          }), ce(u, "link", a), e.state.loading |= 4, Gi(u, l.precedence, t), e.instance = u;
        case "script":
          return u = yn(l.src), (n = t.querySelector(
            du(u)
          )) ? (e.instance = n, Wt(n), n) : (a = l, (n = Ve.get(u)) && (a = V({}, l), Cf(a, n)), t = t.ownerDocument || t, n = t.createElement("script"), Wt(n), ce(n, "link", a), t.head.appendChild(n), e.instance = n);
        case "void":
          return null;
        default:
          throw Error(o(443, e.type));
      }
    else
      e.type === "stylesheet" && (e.state.loading & 4) === 0 && (a = e.instance, e.state.loading |= 4, Gi(a, l.precedence, t));
    return e.instance;
  }
  function Gi(t, e, l) {
    for (var a = l.querySelectorAll(
      'link[rel="stylesheet"][data-precedence],style[data-precedence]'
    ), n = a.length ? a[a.length - 1] : null, u = n, i = 0; i < a.length; i++) {
      var f = a[i];
      if (f.dataset.precedence === e) u = f;
      else if (u !== n) break;
    }
    u ? u.parentNode.insertBefore(t, u.nextSibling) : (e = l.nodeType === 9 ? l.head : l, e.insertBefore(t, e.firstChild));
  }
  function Mf(t, e) {
    t.crossOrigin == null && (t.crossOrigin = e.crossOrigin), t.referrerPolicy == null && (t.referrerPolicy = e.referrerPolicy), t.title == null && (t.title = e.title);
  }
  function Cf(t, e) {
    t.crossOrigin == null && (t.crossOrigin = e.crossOrigin), t.referrerPolicy == null && (t.referrerPolicy = e.referrerPolicy), t.integrity == null && (t.integrity = e.integrity);
  }
  var Qi = null;
  function rh(t, e, l) {
    if (Qi === null) {
      var a = /* @__PURE__ */ new Map(), n = Qi = /* @__PURE__ */ new Map();
      n.set(l, a);
    } else
      n = Qi, a = n.get(l), a || (a = /* @__PURE__ */ new Map(), n.set(l, a));
    if (a.has(t)) return a;
    for (a.set(t, null), l = l.getElementsByTagName(t), n = 0; n < l.length; n++) {
      var u = l[n];
      if (!(u[zn] || u[le] || t === "link" && u.getAttribute("rel") === "stylesheet") && u.namespaceURI !== "http://www.w3.org/2000/svg") {
        var i = u.getAttribute(e) || "";
        i = t + i;
        var f = a.get(i);
        f ? f.push(u) : a.set(i, [u]);
      }
    }
    return a;
  }
  function Rf(t, e, l) {
    t = t.ownerDocument || t, t.head.insertBefore(
      l,
      e === "title" ? t.querySelector("head > title") : null
    );
  }
  function wv(t, e, l) {
    if (l === 1 || e.itemProp != null) return !1;
    switch (t) {
      case "meta":
      case "title":
        return !0;
      case "style":
        if (typeof e.precedence != "string" || typeof e.href != "string" || e.href === "")
          break;
        return !0;
      case "link":
        if (typeof e.rel != "string" || typeof e.href != "string" || e.href === "" || e.onLoad || e.onError)
          break;
        return e.rel === "stylesheet" ? (t = e.disabled, typeof e.precedence == "string" && t == null) : !0;
      case "script":
        if (e.async && typeof e.async != "function" && typeof e.async != "symbol" && !e.onLoad && !e.onError && e.src && typeof e.src == "string")
          return !0;
    }
    return !1;
  }
  function dh(t, e) {
    return t === "img" && e.src != null && e.src !== "" && e.onLoad == null && e.loading !== "lazy";
  }
  function mh(t) {
    return !(t.type === "stylesheet" && (t.state.loading & 3) === 0);
  }
  function hh(t) {
    return (t.width || 100) * (t.height || 100) * (typeof devicePixelRatio == "number" ? devicePixelRatio : 1) * 0.25;
  }
  function yh(t, e) {
    typeof e.decode == "function" && (t.imgCount++, e.complete || (t.imgBytes += hh(e), t.suspenseyImages.push(e)), t = qv.bind(t), e.decode().then(t, t));
  }
  function Hv(t, e, l, a) {
    if (l.type === "stylesheet" && (typeof a.media != "string" || matchMedia(a.media).matches !== !1) && (l.state.loading & 4) === 0) {
      if (l.instance === null) {
        var n = hn(a.href), u = e.querySelector(
          ru(n)
        );
        if (u) {
          e = u._p, e !== null && typeof e == "object" && typeof e.then == "function" && (t.count++, t = mu.bind(t), e.then(t, t)), l.state.loading |= 4, l.instance = u, Wt(u);
          return;
        }
        u = e.ownerDocument || e, a = fh(a), (n = Ve.get(n)) && Mf(a, n), u = u.createElement("link"), Wt(u);
        var i = u;
        i._p = new Promise(function(f, m) {
          i.onload = f, i.onerror = m;
        }), ce(u, "link", a), l.instance = u;
      }
      t.stylesheets === null && (t.stylesheets = /* @__PURE__ */ new Map()), t.stylesheets.set(l, e), (e = l.state.preload) && (l.state.loading & 3) === 0 && (t.count++, l = mu.bind(t), e.addEventListener("load", l), e.addEventListener("error", l));
    }
  }
  var Vi = 0;
  function Bv(t, e) {
    return t.stylesheets && t.count === 0 && Ki(t, t.stylesheets), 0 < t.count || 0 < t.imgCount ? function(l) {
      var a = setTimeout(function() {
        if (t.stylesheets && Ki(t, t.stylesheets), t.unsuspend) {
          var u = t.unsuspend;
          t.unsuspend = null, u();
        }
      }, 6e4 + e);
      0 < t.imgBytes && Vi === 0 && (Vi = 62500 * ev());
      var n = setTimeout(
        function() {
          if (t.waitingForImages = !1, t.count === 0 && (t.stylesheets && Ki(t, t.stylesheets), t.unsuspend)) {
            var u = t.unsuspend;
            t.unsuspend = null, u();
          }
        },
        (t.imgBytes > Vi ? 50 : 800) + e
      );
      return t.unsuspend = l, function() {
        t.unsuspend = null, clearTimeout(a), clearTimeout(n);
      };
    } : null;
  }
  function vh(t) {
    if (t.count === 0 && (t.imgCount === 0 || !t.waitingForImages)) {
      if (t.stylesheets) Ki(t, t.stylesheets);
      else if (t.unsuspend) {
        var e = t.unsuspend;
        t.unsuspend = null, e();
      }
    }
  }
  function mu() {
    this.count--, vh(this);
  }
  function qv() {
    this.imgCount--, vh(this);
  }
  var Zi = null;
  function Ki(t, e) {
    t.stylesheets = null, t.unsuspend !== null && (t.count++, Zi = /* @__PURE__ */ new Map(), e.forEach(Yv, t), Zi = null, mu.call(t));
  }
  function Yv(t, e) {
    if (!(e.state.loading & 4)) {
      var l = Zi.get(t);
      if (l) var a = l.get(null);
      else {
        l = /* @__PURE__ */ new Map(), Zi.set(t, l);
        for (var n = t.querySelectorAll(
          "link[data-precedence],style[data-precedence]"
        ), u = 0; u < n.length; u++) {
          var i = n[u];
          (i.nodeName === "LINK" || i.getAttribute("media") !== "not all") && (l.set(i.dataset.precedence, i), a = i);
        }
        a && l.set(null, a);
      }
      n = e.instance, i = n.getAttribute("data-precedence"), u = l.get(i) || a, u === a && l.set(null, n), l.set(i, n), this.count++, a = mu.bind(this), n.addEventListener("load", a), n.addEventListener("error", a), u ? u.parentNode.insertBefore(n, u.nextSibling) : (t = t.nodeType === 9 ? t.head : t, t.insertBefore(n, t.firstChild)), e.state.loading |= 4;
    }
  }
  var vn = {
    $$typeof: Rt,
    Provider: null,
    Consumer: null,
    _currentValue: Dt,
    _currentValue2: Dt,
    _threadCount: 0
  };
  function Lv(t, e, l, a, n, u, i, f, m) {
    this.tag = 1, this.containerInfo = t, this.pingCache = this.current = this.pendingChildren = null, this.timeoutHandle = -1, this.callbackNode = this.next = this.pendingContext = this.context = this.cancelPendingCommit = null, this.callbackPriority = 0, this.expirationTimes = rc(-1), this.entangledLanes = this.shellSuspendCounter = this.errorRecoveryDisabledLanes = this.expiredLanes = this.warmLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0, this.entanglements = rc(0), this.hiddenUpdates = rc(null), this.identifierPrefix = a, this.onUncaughtError = n, this.onCaughtError = u, this.onRecoverableError = i, this.pooledCache = null, this.pooledCacheLanes = 0, this.formState = m, this.transitionTypes = null, this.incompleteTransitions = /* @__PURE__ */ new Map();
  }
  function gh(t, e, l, a, n, u, i, f, m, x, j, C) {
    return t = new Lv(
      t,
      e,
      l,
      i,
      m,
      x,
      j,
      C,
      f
    ), e = 1, u === !0 && (e |= 24), u = ve(3, null, null, e), t.current = u, u.stateNode = t, e = Kc(), e.refCount++, t.pooledCache = e, e.refCount++, u.memoizedState = {
      element: a,
      isDehydrated: l,
      cache: e
    }, Fc(u), t;
  }
  function ph(t) {
    return t ? (t = Xa, t) : Xa;
  }
  function bh(t, e, l, a, n, u) {
    n = ph(n), a.context === null ? a.context = n : a.pendingContext = n, a = Yl(e), a.payload = { element: l }, u = u === void 0 ? null : u, u !== null && (a.callback = u), l = Ll(t, a, e), l !== null && (xe(l, t, e), Vn(l, t, e));
  }
  function xh(t, e) {
    if (t = t.memoizedState, t !== null && t.dehydrated !== null) {
      var l = t.retryLane;
      t.retryLane = l !== 0 && l < e ? l : e;
    }
  }
  function Df(t, e) {
    xh(t, e), (t = t.alternate) && xh(t, e);
  }
  function Sh(t) {
    if (t.tag === 13 || t.tag === 31) {
      var e = fa(t, 67108864);
      e !== null && xe(e, t, 67108864), Df(t, 67108864);
    }
  }
  function _h(t) {
    if (t.tag === 13 || t.tag === 31) {
      var e = Ce();
      e = dc(e);
      var l = fa(t, e);
      l !== null && xe(l, t, e), Df(t, e);
    }
  }
  var gn = !0;
  function Xv(t, e, l, a) {
    var n = G.T;
    G.T = null;
    var u = W.p;
    try {
      W.p = 2, Uf(t, e, l, a);
    } finally {
      W.p = u, G.T = n;
    }
  }
  function Gv(t, e, l, a) {
    var n = G.T;
    G.T = null;
    var u = W.p;
    try {
      W.p = 8, Uf(t, e, l, a);
    } finally {
      W.p = u, G.T = n;
    }
  }
  function Uf(t, e, l, a) {
    if (gn) {
      var n = wf(a);
      if (n === null)
        yf(
          t,
          e,
          a,
          ki,
          l
        ), Th(t, a);
      else if (Vv(
        n,
        t,
        e,
        l,
        a
      ))
        a.stopPropagation();
      else if (Th(t, a), e & 4 && -1 < Qv.indexOf(t)) {
        for (; n !== null; ) {
          var u = Ma(n);
          if (u !== null)
            switch (u.tag) {
              case 3:
                if (u = u.stateNode, u.current.memoizedState.isDehydrated) {
                  var i = na(u.pendingLanes);
                  if (i !== 0) {
                    var f = u;
                    for (f.pendingLanes |= 2, f.entangledLanes |= 2; i; ) {
                      var m = 1 << 31 - Te(i);
                      f.entanglements[1] |= m, i &= ~m;
                    }
                    ol(u), (_t & 6) === 0 && (Ri = _e() + 500, iu(0));
                  }
                }
                break;
              case 31:
              case 13:
                f = fa(u, 2), f !== null && xe(f, u, 2), wi(), Df(u, 2);
            }
          if (u = wf(a), u === null && yf(
            t,
            e,
            a,
            ki,
            l
          ), u === n) break;
          n = u;
        }
        n !== null && a.stopPropagation();
      } else
        yf(
          t,
          e,
          a,
          null,
          l
        );
    }
  }
  function wf(t) {
    return t = bc(t), Hf(t);
  }
  var ki = null;
  function Hf(t) {
    if (ki = null, t = ua(t), t !== null) {
      var e = D(t);
      if (e === null) t = null;
      else {
        var l = e.tag;
        if (l === 13) {
          if (t = R(e), t !== null) return t;
          t = null;
        } else if (l === 31) {
          if (t = p(e), t !== null) return t;
          t = null;
        } else if (l === 3) {
          if (e.stateNode.current.memoizedState.isDehydrated)
            return e.tag === 3 ? e.stateNode.containerInfo : null;
          t = null;
        } else e !== t && (t = null);
      }
    }
    return ki = t, null;
  }
  function Nh(t) {
    switch (t) {
      case "beforetoggle":
      case "cancel":
      case "click":
      case "close":
      case "contextmenu":
      case "copy":
      case "cut":
      case "auxclick":
      case "dblclick":
      case "dragend":
      case "dragstart":
      case "drop":
      case "focusin":
      case "focusout":
      case "input":
      case "invalid":
      case "keydown":
      case "keypress":
      case "keyup":
      case "mousedown":
      case "mouseup":
      case "paste":
      case "pause":
      case "play":
      case "pointercancel":
      case "pointerdown":
      case "pointerup":
      case "ratechange":
      case "reset":
      case "seeked":
      case "submit":
      case "toggle":
      case "touchcancel":
      case "touchend":
      case "touchstart":
      case "volumechange":
      case "change":
      case "selectionchange":
      case "textInput":
      case "compositionstart":
      case "compositionend":
      case "compositionupdate":
      case "beforeblur":
      case "afterblur":
      case "beforeinput":
      case "blur":
      case "fullscreenchange":
      case "fullscreenerror":
      case "focus":
      case "hashchange":
      case "popstate":
      case "select":
      case "selectstart":
        return 2;
      case "drag":
      case "dragenter":
      case "dragexit":
      case "dragleave":
      case "dragover":
      case "mousemove":
      case "mouseout":
      case "mouseover":
      case "pointermove":
      case "pointerout":
      case "pointerover":
      case "resize":
      case "scroll":
      case "touchmove":
      case "wheel":
      case "mouseenter":
      case "mouseleave":
      case "pointerenter":
      case "pointerleave":
        return 8;
      case "message":
        switch (e0()) {
          case co:
            return 2;
          case so:
            return 8;
          case ju:
          case l0:
            return 32;
          case fo:
            return 268435456;
          default:
            return 32;
        }
      default:
        return 32;
    }
  }
  var Bf = !1, Il = null, Pl = null, ta = null, hu = /* @__PURE__ */ new Map(), yu = /* @__PURE__ */ new Map(), ea = [], Qv = "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset".split(
    " "
  );
  function Th(t, e) {
    switch (t) {
      case "focusin":
      case "focusout":
        Il = null;
        break;
      case "dragenter":
      case "dragleave":
        Pl = null;
        break;
      case "mouseover":
      case "mouseout":
        ta = null;
        break;
      case "pointerover":
      case "pointerout":
        hu.delete(e.pointerId);
        break;
      case "gotpointercapture":
      case "lostpointercapture":
        yu.delete(e.pointerId);
    }
  }
  function vu(t, e, l, a, n, u) {
    return t === null || t.nativeEvent !== u ? (t = {
      blockedOn: e,
      domEventName: l,
      eventSystemFlags: a,
      nativeEvent: u,
      targetContainers: [n]
    }, e !== null && (e = Ma(e), e !== null && Sh(e)), t) : (t.eventSystemFlags |= a, e = t.targetContainers, n !== null && e.indexOf(n) === -1 && e.push(n), t);
  }
  function Vv(t, e, l, a, n) {
    switch (e) {
      case "focusin":
        return Il = vu(
          Il,
          t,
          e,
          l,
          a,
          n
        ), !0;
      case "dragenter":
        return Pl = vu(
          Pl,
          t,
          e,
          l,
          a,
          n
        ), !0;
      case "mouseover":
        return ta = vu(
          ta,
          t,
          e,
          l,
          a,
          n
        ), !0;
      case "pointerover":
        var u = n.pointerId;
        return hu.set(
          u,
          vu(
            hu.get(u) || null,
            t,
            e,
            l,
            a,
            n
          )
        ), !0;
      case "gotpointercapture":
        return u = n.pointerId, yu.set(
          u,
          vu(
            yu.get(u) || null,
            t,
            e,
            l,
            a,
            n
          )
        ), !0;
    }
    return !1;
  }
  function Eh(t) {
    var e = ua(t.target);
    if (e !== null) {
      var l = D(e);
      if (l !== null) {
        if (e = l.tag, e === 13) {
          if (e = R(l), e !== null) {
            t.blockedOn = e, go(t.priority, function() {
              _h(l);
            });
            return;
          }
        } else if (e === 31) {
          if (e = p(l), e !== null) {
            t.blockedOn = e, go(t.priority, function() {
              _h(l);
            });
            return;
          }
        } else if (e === 3 && l.stateNode.current.memoizedState.isDehydrated) {
          t.blockedOn = l.tag === 3 ? l.stateNode.containerInfo : null;
          return;
        }
      }
    }
    t.blockedOn = null;
  }
  function Ji(t) {
    if (t.blockedOn !== null) return !1;
    for (var e = t.targetContainers; 0 < e.length; ) {
      var l = wf(t.nativeEvent);
      if (l === null) {
        l = t.nativeEvent;
        var a = new l.constructor(
          l.type,
          l
        );
        pc = a, l.target.dispatchEvent(a), pc = null;
      } else
        return e = Ma(l), e !== null && Sh(e), t.blockedOn = l, !1;
      e.shift();
    }
    return !0;
  }
  function jh(t, e, l) {
    Ji(t) && l.delete(e);
  }
  function Zv() {
    Bf = !1, Il !== null && Ji(Il) && (Il = null), Pl !== null && Ji(Pl) && (Pl = null), ta !== null && Ji(ta) && (ta = null), hu.forEach(jh), yu.forEach(jh);
  }
  function $i(t, e) {
    t.blockedOn === e && (t.blockedOn = null, Bf || (Bf = !0, c.unstable_scheduleCallback(
      c.unstable_NormalPriority,
      Zv
    )));
  }
  var Fi = null;
  function zh(t) {
    Fi !== t && (Fi = t, c.unstable_scheduleCallback(
      c.unstable_NormalPriority,
      function() {
        Fi === t && (Fi = null);
        for (var e = 0; e < t.length; e += 3) {
          var l = t[e], a = t[e + 1], n = t[e + 2];
          if (typeof a != "function") {
            if (Hf(a || l) === null)
              continue;
            break;
          }
          var u = Ma(l);
          u !== null && (t.splice(e, 3), e -= 3, gs(
            u,
            {
              pending: !0,
              data: n,
              method: l.method,
              action: a
            },
            a,
            n
          ));
        }
      }
    ));
  }
  function pn(t) {
    function e(m) {
      return $i(m, t);
    }
    Il !== null && $i(Il, t), Pl !== null && $i(Pl, t), ta !== null && $i(ta, t), hu.forEach(e), yu.forEach(e);
    for (var l = 0; l < ea.length; l++) {
      var a = ea[l];
      a.blockedOn === t && (a.blockedOn = null);
    }
    for (; 0 < ea.length && (l = ea[0], l.blockedOn === null); )
      Eh(l), l.blockedOn === null && ea.shift();
    if (l = (t.ownerDocument || t).$$reactFormReplay, l != null)
      for (a = 0; a < l.length; a += 3) {
        var n = l[a], u = l[a + 1], i = n[ye] || null;
        if (typeof u == "function")
          i || zh(l);
        else if (i) {
          var f = null;
          if (u && u.hasAttribute("formAction")) {
            if (n = u, i = u[ye] || null)
              f = i.formAction;
            else if (Hf(n) !== null) continue;
          } else f = i.action;
          typeof f == "function" ? l[a + 1] = f : (l.splice(a, 3), a -= 3), zh(l);
        }
      }
  }
  function Ah() {
    function t(u) {
      u.canIntercept && u.info === "react-transition" && u.intercept({
        handler: function() {
          return new Promise(function(i) {
            return n = i;
          });
        },
        focusReset: "manual",
        scroll: "manual"
      });
    }
    function e() {
      n !== null && (n(), n = null), a || setTimeout(l, 20);
    }
    function l() {
      if (!a && !navigation.transition) {
        var u = navigation.currentEntry;
        u && u.url != null && navigation.navigate(u.url, {
          state: u.getState(),
          info: "react-transition",
          history: "replace"
        });
      }
    }
    if (typeof navigation == "object") {
      var a = !1, n = null;
      return navigation.addEventListener("navigate", t), navigation.addEventListener("navigatesuccess", e), navigation.addEventListener("navigateerror", e), setTimeout(l, 100), function() {
        a = !0, navigation.removeEventListener("navigate", t), navigation.removeEventListener("navigatesuccess", e), navigation.removeEventListener("navigateerror", e), n !== null && (n(), n = null);
      };
    }
  }
  function qf(t) {
    this._internalRoot = t;
  }
  Wi.prototype.render = qf.prototype.render = function(t) {
    var e = this._internalRoot;
    if (e === null) throw Error(o(409));
    var l = e.current, a = Ce();
    bh(l, a, t, e, null, null);
  }, Wi.prototype.unmount = qf.prototype.unmount = function() {
    var t = this._internalRoot;
    if (t !== null) {
      this._internalRoot = null;
      var e = t.containerInfo;
      bh(t.current, 2, null, t, null, null), wi(), e[Oa] = null;
    }
  };
  function Wi(t) {
    this._internalRoot = t;
  }
  Wi.prototype.unstable_scheduleHydration = function(t) {
    if (t) {
      var e = vo();
      t = { blockedOn: null, target: t, priority: e };
      for (var l = 0; l < ea.length && e !== 0 && e < ea[l].priority; l++) ;
      ea.splice(l, 0, t), l === 0 && Eh(t);
    }
  };
  var Oh = r.version;
  if (Oh !== "19.3.0")
    throw Error(
      o(
        527,
        Oh,
        "19.3.0"
      )
    );
  W.findDOMNode = function(t) {
    var e = t._reactInternals;
    if (e === void 0)
      throw typeof t.render == "function" ? Error(o(188)) : (t = Object.keys(t).join(","), Error(o(268, t)));
    return t = M(e), t = t !== null ? z(t) : null, t = t === null ? null : t.stateNode, t;
  };
  var Kv = {
    bundleType: 0,
    version: "19.3.0",
    rendererPackageName: "react-dom",
    currentDispatcherRef: G,
    reconcilerVersion: "19.3.0"
  };
  if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ < "u") {
    var Ii = __REACT_DEVTOOLS_GLOBAL_HOOK__;
    if (!Ii.isDisabled && Ii.supportsFiber)
      try {
        Tn = Ii.inject(
          Kv
        ), Ne = Ii;
      } catch {
      }
  }
  return gu.createRoot = function(t, e) {
    if (!h(t)) throw Error(o(299));
    var l = !1, a = "", n = pd, u = bd, i = xd;
    return e != null && (e.unstable_strictMode === !0 && (l = !0), e.identifierPrefix !== void 0 && (a = e.identifierPrefix), e.onUncaughtError !== void 0 && (n = e.onUncaughtError), e.onCaughtError !== void 0 && (u = e.onCaughtError), e.onRecoverableError !== void 0 && (i = e.onRecoverableError)), e = gh(
      t,
      1,
      !1,
      null,
      null,
      l,
      a,
      null,
      n,
      u,
      i,
      Ah
    ), t[Oa] = e.current, hf(t), new qf(e);
  }, gu.hydrateRoot = function(t, e, l) {
    if (!h(t)) throw Error(o(299));
    var a = !1, n = "", u = pd, i = bd, f = xd, m = null;
    return l != null && (l.unstable_strictMode === !0 && (a = !0), l.identifierPrefix !== void 0 && (n = l.identifierPrefix), l.onUncaughtError !== void 0 && (u = l.onUncaughtError), l.onCaughtError !== void 0 && (i = l.onCaughtError), l.onRecoverableError !== void 0 && (f = l.onRecoverableError), l.formState !== void 0 && (m = l.formState)), e = gh(
      t,
      1,
      !0,
      e,
      l ?? null,
      a,
      n,
      m,
      u,
      i,
      f,
      Ah
    ), e.context = ph(null), l = e.current, a = Ce(), a = dc(a), n = Yl(a), n.callback = null, Ll(l, n, a), l = a, e.current.lanes = l, jn(e, l), ol(e), t[Oa] = e.current, hf(t), new Wi(e);
  }, gu.version = "19.3.0", gu;
}
var Bh;
function tg() {
  if (Bh) return Lf.exports;
  Bh = 1;
  function c() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(c);
      } catch (r) {
        console.error(r);
      }
  }
  return c(), Lf.exports = Pv(), Lf.exports;
}
var eg = tg();
function lg(c) {
  const r = c.indexOf("/api/plugins/");
  return r >= 0 ? c.slice(0, r) : "";
}
class to extends Error {
  constructor(r, y) {
    super(y), this.status = r;
  }
  status;
}
async function eo(c, r) {
  const y = await fetch(c, { credentials: "include", signal: r, headers: { Accept: "application/json" } });
  if (!y.ok) {
    let o = `${y.status}`;
    try {
      const h = await y.json();
      typeof h.detail == "string" && (o = h.detail);
    } catch {
    }
    throw new to(y.status, o);
  }
  return await y.json();
}
function qh(c, r, y) {
  return eo(`${c}/api/context-residency/tasks/${encodeURIComponent(r)}`, y);
}
function ag(c) {
  const r = new URLSearchParams(), y = c.query?.trim();
  return y && r.set("query", y), c.kind && r.set("kind", c.kind), c.outcome && r.set("outcome", c.outcome), c.since && r.set("since", c.since), c.hasCompactions && r.set("has_compactions", "true"), c.incompleteOnly && r.set("incomplete_only", "true"), c.sort && r.set("sort", c.sort), c.direction && r.set("direction", c.direction), r.set("limit", String(c.limit)), c.offset && r.set("offset", String(c.offset)), r;
}
function ng(c, r, y) {
  const o = ag(r).toString();
  return eo(`${c}/api/context-residency/tasks${o ? `?${o}` : ""}`, y);
}
function ug(c, r) {
  return eo(`${c}/api/context-residency/health`, r);
}
var Vf = { exports: {} }, pu = {};
var Yh;
function ig() {
  if (Yh) return pu;
  Yh = 1;
  var c = /* @__PURE__ */ Symbol.for("react.transitional.element"), r = /* @__PURE__ */ Symbol.for("react.fragment");
  function y(o, h, D) {
    var R = null;
    if (D !== void 0 && (R = "" + D), h.key !== void 0 && (R = "" + h.key), "key" in h) {
      D = {};
      for (var p in h)
        p !== "key" && (D[p] = h[p]);
    } else D = h;
    return h = D.ref, {
      $$typeof: c,
      type: o,
      key: R,
      ref: h !== void 0 ? h : null,
      props: D
    };
  }
  return pu.Fragment = r, pu.jsx = y, pu.jsxs = y, pu;
}
var Lh;
function cg() {
  return Lh || (Lh = 1, Vf.exports = ig()), Vf.exports;
}
var s = cg();
const sg = (c) => c.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase(), fg = (c) => c.replace(
  /^([A-Z])|[\s-_]+(\w)/g,
  (r, y, o) => o ? o.toUpperCase() : y.toLowerCase()
), Xh = (c) => {
  const r = fg(c);
  return r.charAt(0).toUpperCase() + r.slice(1);
}, Kh = (...c) => c.filter((r, y, o) => !!r && r.trim() !== "" && o.indexOf(r) === y).join(" ").trim(), og = (c) => {
  for (const r in c)
    if (r.startsWith("aria-") || r === "role" || r === "title")
      return !0;
};
var rg = {
  xmlns: "http://www.w3.org/2000/svg",
  width: 24,
  height: 24,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round"
};
const dg = J.forwardRef(
  ({
    color: c = "currentColor",
    size: r = 24,
    strokeWidth: y = 2,
    absoluteStrokeWidth: o,
    className: h = "",
    children: D,
    iconNode: R,
    ...p
  }, q) => J.createElement(
    "svg",
    {
      ref: q,
      ...rg,
      width: r,
      height: r,
      stroke: c,
      strokeWidth: o ? Number(y) * 24 / Number(r) : y,
      className: Kh("lucide", h),
      ...!D && !og(p) && { "aria-hidden": "true" },
      ...p
    },
    [
      ...R.map(([M, z]) => J.createElement(M, z)),
      ...Array.isArray(D) ? D : [D]
    ]
  )
);
const _u = (c, r) => {
  const y = J.forwardRef(
    ({ className: o, ...h }, D) => J.createElement(dg, {
      ref: D,
      iconNode: r,
      className: Kh(
        `lucide-${sg(Xh(c))}`,
        `lucide-${c}`,
        o
      ),
      ...h
    })
  );
  return y.displayName = Xh(c), y;
};
const mg = [["path", { d: "m15 18-6-6 6-6", key: "1wnfg3" }]], kh = _u("chevron-left", mg);
const hg = [["path", { d: "m9 18 6-6-6-6", key: "mthhwq" }]], yg = _u("chevron-right", hg);
const vg = [
  ["path", { d: "M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", key: "v9h5vc" }],
  ["path", { d: "M21 3v5h-5", key: "1q7to0" }],
  ["path", { d: "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", key: "3uifl3" }],
  ["path", { d: "M8 16H3v5", key: "1cv678" }]
], lo = _u("refresh-cw", vg);
const gg = [
  ["circle", { cx: "6", cy: "6", r: "3", key: "1lh9wr" }],
  ["path", { d: "M8.12 8.12 12 12", key: "1alkpv" }],
  ["path", { d: "M20 4 8.12 15.88", key: "xgtan2" }],
  ["circle", { cx: "6", cy: "18", r: "3", key: "fqmcym" }],
  ["path", { d: "M14.8 14.8 20 20", key: "ptml3r" }]
], Jh = _u("scissors", gg);
const pg = [
  ["path", { d: "m21 21-4.34-4.34", key: "14j7rj" }],
  ["circle", { cx: "11", cy: "11", r: "8", key: "4ej97u" }]
], bg = _u("search", pg), xn = [
  "system",
  "tool_schema",
  "memory",
  "skill",
  "user",
  "assistant",
  "tool_result",
  "summary",
  "middleware",
  "attachment",
  "unknown"
];
function ao(c) {
  if (c === null) return "unknown";
  if (c.channel === "tool_schema") return "tool_schema";
  switch (c.kind) {
    case "system_prompt":
      return "system";
    case "tool_schema":
      return "tool_schema";
    case "memory":
      return "memory";
    case "skill_instruction":
      return "skill";
    case "user_input":
      return "user";
    case "assistant_output":
    case "assistant_reasoning":
    case "tool_request":
      return "assistant";
    case "tool_result_raw":
    case "tool_result_visible":
      return "tool_result";
    case "summary":
      return "summary";
    case "middleware_injection":
    case "durable_context":
      return "middleware";
    case "image_or_attachment":
      return "attachment";
    default:
      return "unknown";
  }
}
function xg(c) {
  const r = c.attempts, y = r.map(
    (Y) => new Map(Y.members.map((F) => [F.block_id, F]))
  ), o = [], h = /* @__PURE__ */ new Set();
  for (const Y of r)
    for (const F of Y.members)
      h.has(F.block_id) || (h.add(F.block_id), o.push(F.block_id));
  const D = /* @__PURE__ */ new Map(), R = /* @__PURE__ */ new Map(), p = /* @__PURE__ */ new Map();
  for (const Y of c.compressions) {
    for (const F of Y.removed_block_ids)
      D.has(F) || D.set(F, Y.compression_id);
    for (const F of Y.preserved_block_ids) {
      const B = R.get(F) ?? [];
      B.push(Y.compression_id), R.set(F, B);
    }
    Y.summary_block_id !== null && !p.has(Y.summary_block_id) && p.set(Y.summary_block_id, Y.compression_id);
  }
  const q = o.map((Y) => {
    const F = c.blocks[Y] ?? null, B = [], Q = [], rt = [];
    let nt = -1, wt = -1, bt = 0, ft = 0, dt = 0;
    return r.forEach((V, k) => {
      const qt = y[k].get(Y);
      if (qt !== void 0) {
        B.push("present"), bt += 1, ft = qt.estimated_tokens, dt = qt.visible_bytes, nt === -1 && (nt = k), wt = k;
        const xt = Q[Q.length - 1];
        xt?.end === k - 1 ? xt.end = k : Q.push({ start: k, end: k });
      } else V.status === "incomplete" ? (B.push("unknown"), rt.push(k)) : B.push("absent");
    }), {
      blockId: Y,
      meta: F,
      lane: ao(F),
      presence: B,
      runs: Q,
      unknownAt: rt,
      firstSeen: nt,
      lastSeen: wt,
      presentCount: bt,
      sizeTokens: ft,
      sizeBytes: dt,
      removedBy: D.get(Y) ?? null,
      preservedBy: R.get(Y) ?? [],
      summaryOf: p.get(Y) ?? null
    };
  }), M = /* @__PURE__ */ new Map();
  for (const Y of q) {
    const F = M.get(Y.lane) ?? [];
    F.push(Y), M.set(Y.lane, F);
  }
  const z = xn.filter((Y) => M.has(Y)).map(
    (Y) => ({ lane: Y, rows: M.get(Y) })
  ), N = /* @__PURE__ */ new Map(), w = [];
  for (const Y of c.compressions) {
    const F = Y.positioned_before_attempt_id;
    if (F !== null && r.some((B) => B.attempt_id === F)) {
      const B = N.get(F) ?? [];
      B.push(Y), N.set(F, B);
    } else
      w.push(Y);
  }
  return {
    attempts: r,
    rows: q,
    lanes: z,
    compressions: c.compressions,
    compressionsBefore: N,
    unanchoredCompressions: w,
    attemptsTruncated: c.attempts_truncated
  };
}
function za(c, r) {
  return r === "tokens" ? c.estimated_tokens : c.visible_bytes;
}
function Sg(c, r, y) {
  return r === "context" ? c : [...c].sort(
    (o, h) => za(h, y) - za(o, y)
  );
}
function tc(c, r) {
  return r === "tokens" ? c.estimated_tokens : c.visible_bytes;
}
function Wf(c, r, y) {
  const o = /* @__PURE__ */ new Map();
  for (const h of c.members) {
    const D = ao(r[h.block_id] ?? null);
    o.set(D, (o.get(D) ?? 0) + za(h, y));
  }
  return xn.filter((h) => o.has(h)).map((h) => ({
    lane: h,
    size: o.get(h)
  }));
}
const _g = 4;
function Ng(c, r, y, o) {
  const h = typeof y == "number" && y > 0 ? y : null;
  if (h === null)
    return {
      basis: "request",
      capacity: null,
      used: r,
      usedShare: null,
      freeShare: null,
      overflow: !1,
      segments: c.map(({ lane: q, size: M }) => {
        const z = r > 0 ? M / r : 0;
        return { lane: q, size: M, share: z, width: z };
      })
    };
  const D = o === "tokens" ? h : h * _g, R = r / D, p = r > D;
  return {
    basis: "window",
    capacity: D,
    used: r,
    usedShare: R,
    freeShare: Math.max(0, 1 - R),
    overflow: p,
    segments: c.map(({ lane: q, size: M }) => ({
      lane: q,
      size: M,
      share: M / D,
      width: p ? r > 0 ? M / r : 0 : M / D
    }))
  };
}
function Tg(c) {
  const r = /* @__PURE__ */ new Map();
  for (const y of c) {
    const o = r.get(y.thread_id);
    o ? o.push(y) : r.set(y.thread_id, [y]);
  }
  return [...r].map(([y, o]) => {
    const h = o.filter((M) => M.kind === "lead"), D = o.filter((M) => M.kind !== "lead"), R = [], p = /* @__PURE__ */ new Set();
    for (const M of h) {
      R.push({ task: M, depth: 0 });
      for (const z of D)
        z.parent_task_id === M.task_id && (R.push({ task: z, depth: 1 }), p.add(z.task_id));
    }
    for (const M of D) p.has(M.task_id) || R.push({ task: M, depth: 1 });
    const q = o.reduce((M, z) => M === null || z.started_at > M ? z.started_at : M, null);
    return { threadId: y, rows: R, latestStartedAt: q };
  });
}
function Eg(c, r) {
  const y = c === "24h" ? 24 : c === "7d" ? 168 : null;
  return y === null ? null : new Date(r.getTime() - y * 36e5).toISOString().replace("Z", "000+00:00");
}
function jg(c) {
  return `${c.toISOString().slice(0, 16)}Z`;
}
function zg(c, r, y = 60) {
  const o = new Map(c.map((D) => [D.minute, D.events])), h = [];
  for (let D = y - 1; D >= 0; D -= 1) {
    const R = jg(new Date(r.getTime() - D * 6e4));
    h.push({ minute: R, events: o.get(R) ?? 0 });
  }
  return h;
}
function Ag(c, r, y, o = 4) {
  const h = Math.max(1, ...c), D = c.length, R = (z) => D <= 1 ? o : o + z / (D - 1) * (r - o * 2), p = (z) => y - o - z / h * (y - o * 2), q = c.map((z, N) => `${N === 0 ? "M" : "L"}${R(N).toFixed(1)} ${p(z).toFixed(1)}`).join(" "), M = D > 0 ? `${q} L${R(D - 1).toFixed(1)} ${p(0).toFixed(1)} L${R(0).toFixed(1)} ${p(0).toFixed(1)} Z` : "";
  return { line: q, area: M, max: h };
}
function Og(c) {
  return c.some((r) => r.level === "error") ? "error" : c.some((r) => r.level === "warning") ? "warning" : "ok";
}
function Mg(c) {
  const r = /* @__PURE__ */ new Map();
  for (const [y, o] of Object.entries(c)) {
    const h = ao({ kind: y, channel: y === "tool_schema" ? "tool_schema" : "message" });
    r.set(h, (r.get(h) ?? 0) + o);
  }
  return xn.filter((y) => r.has(y)).map((y) => ({ lane: y, size: r.get(y) }));
}
function Cg(c) {
  return c >= 1e6 ? `${(c / 1e6).toFixed(1)}M` : c >= 1e3 ? `${(c / 1e3).toFixed(1)}k` : String(c);
}
function aa(c, r = 1) {
  const y = c * 100, o = 10 ** -r;
  return y > 0 && y < o / 2 ? `<${o.toFixed(r)}%` : `${y.toFixed(r)}%`;
}
function Rg(c) {
  return c >= 1073741824 ? `${(c / 1073741824).toFixed(1)} GB` : c >= 1048576 ? `${(c / 1048576).toFixed(1)} MB` : c >= 1024 ? `${(c / 1024).toFixed(1)} KB` : `${c} B`;
}
function Dg(c, r) {
  if (!c) return null;
  const y = new Date(c).getTime();
  return Number.isNaN(y) ? null : Math.max(0, Math.round((r.getTime() - y) / 1e3));
}
function $h(c) {
  return { title: c.title, detail: c.detail, remedy: c.remedy };
}
const Ug = {
  title: "Context residency",
  empty: "No recorded model requests for this task.",
  attemptsTruncated: "Attempt list truncated at the server cap — the earliest attempts are shown.",
  coverage: "Presence is derived from recorded request inventories only. Absence inside an incomplete inventory renders as unknown — never as removal — and removal causes come only from recorded compaction memberships.",
  refresh: "Refresh",
  hint: "⌘/Ctrl+wheel zoom · drag the minimap to zoom, click to reset · ←/→ attempt",
  laneSystem: "System prompt",
  laneToolSchema: "Tool schema",
  laneMemory: "Memory",
  laneSkill: "Skill",
  laneUser: "User input",
  laneAssistant: "Assistant",
  laneToolResult: "Tool result",
  laneSummary: "Summary",
  laneMiddleware: "Middleware injection",
  laneAttachment: "Attachment",
  laneUnknown: "Unknown",
  lowerBound: "lower bound",
  composition: "Composition",
  compression: "Compaction",
  snapshot: "Request",
  retryAttempt: "retry attempt",
  total: "Total",
  members: "Ordered members",
  sortContext: "Context order",
  sortShare: "By share",
  memberUnprojected: "block not recorded",
  incompleteNote: "This inventory is incomplete: members that could not be serialized are missing, so the total is a lower bound and absences here are unknown, not removals.",
  unanchored: "Not positioned on the attempt stream",
  block: "Block",
  residence: "Residence",
  firstSeen: "First seen",
  lastSeen: "Last seen",
  removedBy: "Removed by",
  continuesIn: "continues in",
  removalUnrecorded: "no recorded removal cause",
  stillPresent: "Present in the latest recorded request.",
  preservedBy: "Preserved by",
  summaryOf: "Summary of",
  positionedBefore: "positioned before",
  compressionScope: "Request totals across the boundary",
  removed: "Removed",
  preserved: "Preserved",
  summaryBlock: "Summary carrier",
  summaryBlockUnknown: "No later request declared this summary.",
  loading: "Loading…",
  loadFailed: "Could not load the recording.",
  tasks: "Recorded tasks",
  noTasks: "No recorded tasks for this conversation.",
  threadLabel: "Conversation id",
  taskLabel: "Task id",
  load: "Load",
  taskKindLead: "lead",
  taskKindSubagent: "subagent",
  recordingOff: "The extension is not recording (no database, or disabled).",
  dropped: (c) => `${c} event(s) were dropped by the recorder; some inventories may be missing.`,
  compositionWindow: (c) => `100% = context window ${c}`,
  compositionRequest: "100% = this request (window not recorded)",
  used: "Used",
  free: "Free",
  overflow: (c) => `${c} over the window`,
  membersOfRequest: "share of this request",
  lede: "Find the task first, then open its board. The extension's own recording state lives under Health: queue, drops, write failures and inventory completeness say whether the recording can be trusted.",
  tabTasks: "Tasks",
  tabHealth: "Health",
  tabBoard: "Board",
  noTaskSelected: "no task selected",
  backToList: "Back to the list",
  searchPlaceholder: "Find by task id, conversation id or agent name; paste a full task id to open it",
  searchNotFound: (c) => `No recorded task ${c}.`,
  allKinds: "All kinds",
  allOutcomes: "All outcomes",
  outcomeRunning: "running",
  outcomeCompleted: "completed",
  outcomeFailed: "failed",
  outcomeAborted: "aborted",
  range24h: "Last 24 hours",
  range7d: "Last 7 days",
  rangeAll: "All time",
  onlyCompactions: "With compactions",
  onlyIncomplete: "With incomplete inventories",
  groupByThread: "By conversation",
  flat: "Flat",
  colTask: "Task",
  colThread: "Conversation",
  colStarted: "Started",
  colDuration: "Duration",
  colSteps: "Steps / attempts",
  colCompactions: "Compactions",
  colInventory: "Inventory",
  colPeak: "Peak context",
  colOutcome: "Outcome",
  openBoard: "Open board",
  openInChat: "Open conversation",
  summaryTasks: (c) => `${c} task(s)`,
  summaryThreads: (c) => `${c} conversation(s)`,
  summaryRunning: (c) => `${c} running`,
  summaryCompactions: (c) => `${c} compaction(s)`,
  summaryIncomplete: (c) => `${c} task(s) with incomplete inventories`,
  onThisPage: "on this page",
  emptyList: "No matching tasks. A task that was not recorded does not appear here — that does not mean it did not happen.",
  showAllTime: "Show all time",
  pageInfo: (c, r, y, o) => `Showing ${c}–${r} of ${y} tasks · ${o} per page`,
  retries: (c) => `${c} retry attempt(s)`,
  inventoryComplete: "complete",
  inventoryIncomplete: (c) => `${c} incomplete`,
  runningFor: (c) => `running · ${c}`,
  tasksInThread: (c) => `${c} task(s)`,
  latest: "latest",
  peakOfWindow: (c) => `${c} of the window`,
  peakStackTitle: "Peak request by lane",
  justNow: "just now",
  minutesAgo: (c) => `${c} min ago`,
  hoursAgo: (c) => `${c} h ago`,
  daysAgo: (c) => `${c} d ago`,
  seconds: (c) => `${c} s`,
  minutes: (c) => `${c} min`,
  hoursMinutes: (c, r) => `${c} h ${r} min`,
  recording: "Recording",
  notRecording: "Not recording",
  recordingDisabled: "Disabled",
  database: "Database",
  tablePrefix: "Table prefix",
  lastWrite: "Last write",
  lastEvent: "Last event",
  uptime: "Up for",
  never: "never",
  refreshedAt: (c) => `Refreshed ${c}`,
  queueDepth: "Queue depth",
  flushEvery: (c) => `flushed every ${c} ms`,
  accepted: "Accepted",
  sinceStart: "events since the service started",
  written: "Written",
  lastBatch: (c, r) => `last batch ${c} in ${r} ms`,
  noBatchYet: "nothing written yet",
  droppedTile: "Dropped",
  lastDropAt: (c) => `last at ${c}, buffer full`,
  noDrops: "no drops",
  writeFailures: "Write failures",
  writeFailuresSub: "a failed batch is dropped whole and counted",
  estimator: "Estimator",
  readCap: (c) => `read cap ${c} attempts / task`,
  throughput: "Write throughput",
  throughputSub: "events written per minute · last 60 minutes",
  peakPerMinute: "Peak",
  currentPerMinute: "This minute",
  perMinute: (c) => `${c} / min`,
  storage: "Storage",
  storageSub: "the four tables the extension owns",
  rows: (c) => `${c} rows`,
  openTasks: (c) => `${c} open`,
  avgPerTask: (c) => `avg ${c} / task`,
  avgPerAttempt: (c) => `avg ${c} / attempt`,
  databaseFile: "Database",
  earliestRecord: "Earliest record",
  retention: "Retention",
  retentionNone: "not configured (v1 keeps everything)",
  noStorage: "No database: nothing is stored and reads answer 503.",
  quality: "Data quality",
  qualitySub: "can the recording be trusted",
  qComplete: "Attempts with a complete inventory",
  qIncomplete: "Incomplete inventories (a member could not be serialized)",
  qPositioned: "Compactions positioned on an attempt stream",
  qUnanchored: "Unanchored compactions (no task identity, or no later request)",
  qStale: (c) => `Tasks without a stop event for over ${c} min`,
  diagnostics: "Diagnostics",
  items: (c) => `${c} item(s)`,
  remedy: "What to do",
  affectedTasks: "Affected tasks",
  configEcho: "Configuration",
  configEchoSub: "the plugins record from config.yaml, read-only",
  extensionVersion: "Extension version",
  apiVersion: "Extension API",
  placements: "Probe placement",
  unknownVersion: "not installed as a package",
  notConfigured: "not set",
  diagnosticCopy: $h
}, wg = {
  title: "上下文留存",
  empty: "该任务没有记录到模型请求。",
  attemptsTruncated: "attempt 列表已在服务端上限截断——展示最早的 attempts。",
  coverage: "存在性仅由已记录的请求成员清单推导。不完整清单中的缺席渲染为未知——从不作移出断言——移出原因只来自已记录的压缩成员关系。",
  refresh: "刷新",
  hint: "⌘/Ctrl+滚轮 缩放 · minimap 拖拽圈选 / 单击复位 · ←/→ 切换 attempt",
  laneSystem: "系统提示",
  laneToolSchema: "工具 Schema",
  laneMemory: "Memory 注入",
  laneSkill: "Skill 注入",
  laneUser: "用户输入",
  laneAssistant: "助手消息",
  laneToolResult: "工具结果",
  laneSummary: "压缩摘要",
  laneMiddleware: "Middleware 注入",
  laneAttachment: "附件",
  laneUnknown: "未知",
  lowerBound: "下界",
  composition: "组成占比",
  compression: "压缩",
  snapshot: "请求",
  retryAttempt: "重试 attempt",
  total: "合计",
  members: "有序成员",
  sortContext: "上下文顺序",
  sortShare: "按占比",
  memberUnprojected: "块未记录",
  incompleteNote: "这份清单不完整：无法序列化的成员缺失，合计只是下界，这里的缺席是未知而不是移出。",
  unanchored: "未定位到 attempt 流",
  block: "块",
  residence: "留存",
  firstSeen: "首见",
  lastSeen: "末见",
  removedBy: "移出于",
  continuesIn: "延续为",
  removalUnrecorded: "移出原因未记录",
  stillPresent: "仍在最新记录的请求中。",
  preservedBy: "被保留于",
  summaryOf: "摘要自",
  positionedBefore: "定位在",
  compressionScope: "边界两侧的请求合计",
  removed: "移出",
  preserved: "保留",
  summaryBlock: "摘要承载块",
  summaryBlockUnknown: "之后的请求没有声明这条摘要。",
  loading: "加载中…",
  loadFailed: "无法加载记录。",
  tasks: "已记录的任务",
  noTasks: "该会话没有记录到任务。",
  threadLabel: "会话 id",
  taskLabel: "任务 id",
  load: "加载",
  taskKindLead: "主代理",
  taskKindSubagent: "子代理",
  recordingOff: "扩展未在记录（没有数据库，或已禁用）。",
  dropped: (c) => `记录器丢弃了 ${c} 个事件；部分清单可能缺失。`,
  compositionWindow: (c) => `100% = 上下文窗口 ${c}`,
  compositionRequest: "100% = 本次请求（未记录窗口大小）",
  used: "已用",
  free: "剩余",
  overflow: (c) => `超出窗口 ${c}`,
  membersOfRequest: "占本次请求",
  lede: "先找到要看的任务，再进看板。扩展自己的记录状态放在「健康度」里：队列、丢弃、写入失败、清单完整度，一眼能看出记录是否可信。",
  tabTasks: "任务列表",
  tabHealth: "健康度",
  tabBoard: "看板",
  noTaskSelected: "未选任务",
  backToList: "返回列表",
  searchPlaceholder: "按任务 id、会话 id 或 agent 名称定位；粘贴完整任务 id 直接打开",
  searchNotFound: (c) => `没有记录到任务 ${c}。`,
  allKinds: "全部类型",
  allOutcomes: "全部结果",
  outcomeRunning: "进行中",
  outcomeCompleted: "完成",
  outcomeFailed: "失败",
  outcomeAborted: "中止",
  range24h: "最近 24 小时",
  range7d: "最近 7 天",
  rangeAll: "全部",
  onlyCompactions: "只看有压缩的",
  onlyIncomplete: "只看清单不完整的",
  groupByThread: "按会话分组",
  flat: "平铺",
  colTask: "任务",
  colThread: "会话",
  colStarted: "开始",
  colDuration: "时长",
  colSteps: "步 / attempt",
  colCompactions: "压缩",
  colInventory: "清单完整度",
  colPeak: "峰值上下文",
  colOutcome: "结果",
  openBoard: "打开看板",
  openInChat: "在会话中打开",
  summaryTasks: (c) => `${c} 个任务`,
  summaryThreads: (c) => `${c} 个会话`,
  summaryRunning: (c) => `${c} 个进行中`,
  summaryCompactions: (c) => `${c} 次压缩`,
  summaryIncomplete: (c) => `${c} 个任务有不完整清单`,
  onThisPage: "本页",
  emptyList: "没有匹配的任务。没有记录的任务不会出现在这里，这不代表它没有发生。",
  showAllTime: "查看全部时间",
  pageInfo: (c, r, y, o) => `显示 ${c}–${r}，共 ${y} 个任务 · 每页 ${o}`,
  retries: (c) => `含 ${c} 个重试 attempt`,
  inventoryComplete: "完整",
  inventoryIncomplete: (c) => `${c} 不完整`,
  runningFor: (c) => `进行中 ${c}`,
  tasksInThread: (c) => `${c} 个任务`,
  latest: "最近",
  peakOfWindow: (c) => `占窗口 ${c}`,
  peakStackTitle: "峰值请求按道组成",
  justNow: "刚刚",
  minutesAgo: (c) => `${c} 分钟前`,
  hoursAgo: (c) => `${c} 小时前`,
  daysAgo: (c) => `${c} 天前`,
  seconds: (c) => `${c} 秒`,
  minutes: (c) => `${c} 分`,
  hoursMinutes: (c, r) => `${c} 小时 ${r} 分`,
  recording: "正在记录",
  notRecording: "未在记录",
  recordingDisabled: "已禁用",
  database: "数据库",
  tablePrefix: "表前缀",
  lastWrite: "最近写入",
  lastEvent: "最近事件",
  uptime: "服务已运行",
  never: "从未",
  refreshedAt: (c) => `已刷新 ${c}`,
  queueDepth: "队列深度",
  flushEvery: (c) => `每 ${c} ms 刷盘一次`,
  accepted: "已接收",
  sinceStart: "事件，自服务启动起",
  written: "已写入",
  lastBatch: (c, r) => `最近一批 ${c} 条，耗时 ${r} ms`,
  noBatchYet: "尚未写入",
  droppedTile: "已丢弃",
  lastDropAt: (c) => `最近一次 ${c}，队列满`,
  noDrops: "没有丢弃",
  writeFailures: "写入失败",
  writeFailuresSub: "失败会整批丢弃并计数",
  estimator: "估算器",
  readCap: (c) => `读取上限 ${c} attempt / 任务`,
  throughput: "写入吞吐",
  throughputSub: "每分钟写入的事件数 · 最近 60 分钟",
  peakPerMinute: "峰值",
  currentPerMinute: "当前",
  perMinute: (c) => `${c} / 分钟`,
  storage: "存储",
  storageSub: "扩展自建的四张表",
  rows: (c) => `${c} 行`,
  openTasks: (c) => `${c} 个进行中`,
  avgPerTask: (c) => `平均 ${c} / 任务`,
  avgPerAttempt: (c) => `平均 ${c} / attempt`,
  databaseFile: "数据库文件",
  earliestRecord: "最早记录",
  retention: "保留策略",
  retentionNone: "未配置（v1 不清理）",
  noStorage: "没有数据库：什么都没有存，读取会返回 503。",
  quality: "数据质量",
  qualitySub: "记录能不能信",
  qComplete: "清单完整的 attempt",
  qIncomplete: "不完整清单（成员序列化失败）",
  qPositioned: "已定位到 attempt 流的压缩",
  qUnanchored: "未定位压缩（事件无 task 身份或没有后续请求）",
  qStale: (c) => `超过 ${c} 分钟没有结束事件的任务`,
  diagnostics: "诊断",
  items: (c) => `${c} 项`,
  remedy: "处理",
  affectedTasks: "受影响任务",
  configEcho: "配置回显",
  configEchoSub: "来自 config.yaml 的 plugins 记录，只读",
  extensionVersion: "扩展版本",
  apiVersion: "扩展 API",
  placements: "探针放置",
  unknownVersion: "未以包形式安装",
  notConfigured: "未设置",
  diagnosticCopy: (c, r) => {
    const y = r.status, o = r.quality;
    switch (c.code) {
      case "not_recording":
        return {
          title: "未在记录",
          detail: "服务没有数据库会话工厂（database.backend 是 memory，或服务启动失败）。采集已关闭，读取会返回 503。",
          remedy: "配置 sqlite 或 postgres 数据库后端并重启 Gateway。"
        };
      case "write_failures":
        return {
          title: "写入失败",
          detail: `${y.write_failures} 个事件在数据库写入失败后丢失。失败会整批丢弃，受影响的任务会缺 attempt。`,
          remedy: "查看 Gateway 日志中的数据库错误；下一次刷盘会继续写入更新的事件。"
        };
      case "events_dropped":
        return {
          title: `缓冲区满，丢弃了 ${y.dropped} 个事件`,
          detail: `${y.last_drop_at ? `最近一次丢弃在 ${y.last_drop_at}。` : ""}缓冲区容量 ${y.queue_capacity ?? "?"} 个事件。受影响的任务读出来会缺 attempt，缺席按未知渲染，不按移出。`,
          remedy: "提高 queue_capacity，或调低 flush_interval_ms 让写入线程更快清空缓冲。"
        };
      case "queue_pressure":
        return {
          title: "缓冲区接近满载",
          detail: `${y.queue_depth} / ${y.queue_capacity ?? "?"} 个事件在等待写入。`,
          remedy: "调低 flush_interval_ms，或检查数据库是否跟得上。"
        };
      case "stale_tasks":
        return {
          title: `${o?.tasks_stale ?? 0} 个任务超过 ${o?.stale_after_minutes ?? 0} 分钟没有结束事件`,
          detail: "可能仍在运行，也可能宿主在 3 秒预算内跳过了生命周期通知。",
          remedy: "记录本身无需处理；结果一栏保持「进行中」，不做猜测。"
        };
      case "unanchored_compactions":
        return {
          title: "有压缩没有定位到 attempt 流",
          detail: `${o?.compactions_unanchored ?? 0} / ${o?.compactions_total ?? 0} 次压缩无法定位：事件没有带 task 身份（宿主早于扩展 API 0.2.5），或之后没有请求。`,
          remedy: "升级宿主，让 CompactionEvent 带上 task_id；未定位的压缩只列出，不猜到矩阵上。"
        };
      case "incomplete_inventories":
        return {
          title: "有清单不完整的 attempt",
          detail: `${o?.attempts_incomplete ?? 0} / ${o?.attempts_total ?? 0} 个 attempt 的清单没能完整序列化。它们的合计只是下界，缺席是未知。`,
          remedy: null
        };
      case "contract":
        return c.level === "ok" ? {
          title: "宿主契约匹配",
          detail: `extension API ${r.config.api_version ?? "?"}：压缩事件带 task 身份与 kept hashes，摘要承载块声明 summary_content_hash。`,
          remedy: null
        } : { title: "契约包缺失", detail: "无法导入 deerflow_extension_api。", remedy: "连同依赖重新安装扩展。" };
      default:
        return $h(c);
    }
  }
};
function Hg(c) {
  return c?.toLowerCase().startsWith("zh") ? wg : Ug;
}
function _n(c, r) {
  if (!c) return "—";
  const y = new Date(c);
  return Number.isNaN(y.getTime()) ? c : new Intl.DateTimeFormat(r?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(y);
}
function Zf(c, r) {
  if (!c) return "—";
  const y = new Date(c);
  return Number.isNaN(y.getTime()) ? c : new Intl.DateTimeFormat(r?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US", { timeStyle: "medium" }).format(y);
}
function he(c, r = 8) {
  return c.length <= r ? c : c.slice(0, r);
}
function Su(c, r, y) {
  if (!c) return y.never;
  const o = new Date(c).getTime();
  if (Number.isNaN(o)) return c;
  const h = Math.max(0, Math.round((r.getTime() - o) / 1e3));
  return h < 60 ? y.justNow : h < 3600 ? y.minutesAgo(Math.round(h / 60)) : h < 86400 ? y.hoursAgo(Math.round(h / 3600)) : y.daysAgo(Math.round(h / 86400));
}
function If(c, r) {
  return c < 60 ? r.seconds(c) : c < 3600 ? r.minutes(Math.round(c / 60)) : r.hoursMinutes(Math.floor(c / 3600), Math.round(c % 3600 / 60));
}
function Fh(c) {
  var r, y, o = "";
  if (typeof c == "string" || typeof c == "number") o += c;
  else if (typeof c == "object") if (Array.isArray(c)) {
    var h = c.length;
    for (r = 0; r < h; r++) c[r] && (y = Fh(c[r])) && (o && (o += " "), o += y);
  } else for (y in c) c[y] && (o && (o += " "), o += y);
  return o;
}
function Bg() {
  for (var c, r, y = 0, o = "", h = arguments.length; y < h; y++) (c = arguments[y]) && (r = Fh(c)) && (o && (o += " "), o += r);
  return o;
}
function ut(...c) {
  return Bg(c);
}
const qg = {
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "hover:bg-muted",
  outline: "border bg-background hover:bg-muted"
};
function rl({ variant: c = "outline", size: r, className: y, type: o = "button", ...h }) {
  return /* @__PURE__ */ s.jsx(
    "button",
    {
      type: o,
      className: ut(
        "inline-flex items-center justify-center gap-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50",
        r === "sm" ? "h-8 px-3 text-xs" : "h-9 px-4",
        qg[c],
        y
      ),
      ...h
    }
  );
}
function ec({ className: c, ...r }) {
  return /* @__PURE__ */ s.jsx("span", { className: ut("inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium", c), ...r });
}
function Kf({ className: c, ...r }) {
  return /* @__PURE__ */ s.jsx("div", { className: ut("bg-muted animate-pulse rounded-md", c), ...r });
}
const kf = 96, Yg = 56, Jf = 4, Ze = {
  system: "bg-indigo-500/75",
  tool_schema: "bg-slate-400/60",
  memory: "bg-violet-500/75",
  skill: "bg-teal-500/75",
  user: "bg-sky-500/75",
  assistant: "bg-blue-500/75",
  tool_result: "bg-cyan-500/70",
  summary: "bg-purple-500/75",
  middleware: "bg-slate-500/70",
  attachment: "bg-slate-400/50",
  unknown: "bg-muted-foreground/30"
}, Gh = {
  system: "#6366f1",
  tool_schema: "#94a3b8",
  memory: "#8b5cf6",
  skill: "#14b8a6",
  user: "#0ea5e9",
  assistant: "#3b82f6",
  tool_result: "#06b6d4",
  summary: "#a855f7",
  middleware: "#64748b",
  attachment: "#94a3b8",
  unknown: "#94a3b8"
}, Qh = "bg-[repeating-linear-gradient(135deg,transparent_0_4px,var(--color-border)_4px_6px)]";
function De(c, r) {
  return r === "tokens" ? c >= 1e3 ? `${(c / 1e3).toFixed(1)}k` : String(c) : c >= 1024 ? `${(c / 1024).toFixed(1)} KB` : `${c} B`;
}
function Lg(c, r) {
  return r <= 0 ? "—" : `${(c / r * 100).toFixed(1)}%`;
}
function Ue(c) {
  const r = `S${c.step_seq}`;
  return c.attempt_no > 1 ? `${r}·a${c.attempt_no}` : r;
}
function Sn(c, r) {
  switch (r) {
    case "system":
      return c.laneSystem;
    case "tool_schema":
      return c.laneToolSchema;
    case "memory":
      return c.laneMemory;
    case "skill":
      return c.laneSkill;
    case "user":
      return c.laneUser;
    case "assistant":
      return c.laneAssistant;
    case "tool_result":
      return c.laneToolResult;
    case "summary":
      return c.laneSummary;
    case "middleware":
      return c.laneMiddleware;
    case "attachment":
      return c.laneAttachment;
    case "unknown":
      return c.laneUnknown;
  }
}
function ac(c, r) {
  return r.meta?.name ? r.meta.name : r.meta?.kind ? r.meta.kind : `${c.block} ${he(r.blockId)}`;
}
function Xg({
  response: c,
  locale: r,
  t: y,
  onRefresh: o,
  refreshing: h,
  seedStepSeq: D
}) {
  const R = J.useMemo(() => xg(c), [c]), [p, q] = J.useState("tokens"), [M, z] = J.useState(() => {
    if (D != null) {
      const A = R.attempts.findIndex((_) => _.step_seq === D && _.effective), d = R.attempts.findIndex((_) => _.step_seq === D), E = A >= 0 ? A : d;
      if (E >= 0) return E;
    }
    return R.attempts.length > 0 ? R.attempts.length - 1 : null;
  }), [N, w] = J.useState({ mode: "attempt" }), [Y, F] = J.useState(() => new Set(xn)), B = R.attempts.length, Q = J.useMemo(
    () => Math.max(1, ...R.attempts.map((A) => tc(A, p))),
    [R.attempts, p]
  ), rt = J.useMemo(
    () => R.attempts.flatMap((A, d) => R.compressionsBefore.has(A.attempt_id) ? [d] : []),
    [R]
  ), nt = J.useRef(null), wt = J.useRef(null), bt = J.useRef(24), ft = J.useRef(Jf), dt = J.useRef(0), V = J.useCallback(() => {
    const A = wt.current;
    if (!A) return;
    const d = bt.current;
    A.dataset.density = d < 16 ? "dense" : d < 34 ? "mid" : "full";
    const E = d >= 34 ? 1 : Math.max(1, Math.ceil(38 / d));
    A.querySelectorAll("[data-attempt-header]").forEach((_, U) => {
      _.dataset.lbl = U % E === 0 ? "on" : "off";
    });
  }, []), k = J.useRef(null), qt = J.useRef(null), xt = J.useRef(null), Yt = J.useRef(null), Lt = J.useRef(null), Ht = J.useCallback(() => {
    const A = nt.current, d = k.current, E = xt.current;
    if (!A || !d || B === 0 || Lt.current?.mode === "select") return;
    const _ = bt.current, U = dt.current, H = Math.max(0, A.scrollLeft / _), K = Math.min(B, (A.scrollLeft + A.clientWidth - U) / _);
    if (d.style.left = `${H / B * 100}%`, d.style.width = `${Math.max(0.4, K - H) / B * 100}%`, E) {
      const et = R.attempts[Math.min(B - 1, Math.floor(H))], G = R.attempts[Math.min(B - 1, Math.max(0, Math.ceil(K) - 1))];
      et && G && (E.textContent = `${Ue(et)} – ${Ue(G)} · ${Math.round(K - H)}/${B}`);
    }
  }, [B, R.attempts]), $t = J.useCallback(
    (A, d, E) => {
      const _ = nt.current, U = wt.current;
      if (!_ || !U) return;
      const H = Math.max(ft.current, Math.min(Yg, A));
      bt.current = H, U.style.setProperty("--residency-colw", `${H}px`), d !== void 0 && E !== void 0 && (_.scrollLeft = Math.max(0, dt.current + d * H - E)), V(), Ht();
    },
    [Ht, V]
  ), Rt = J.useCallback(() => {
    const A = nt.current;
    return !A || B === 0 ? Jf : Math.max(Jf, Math.floor((A.clientWidth - dt.current) / B));
  }, [B]);
  J.useEffect(() => {
    const A = nt.current, d = wt.current;
    if (!A || !d || B === 0) return;
    const E = d.querySelector("[data-residency-label]");
    dt.current = E?.offsetWidth ?? 0, ft.current = Rt(), $t(ft.current), A.scrollLeft = 0;
    const _ = new ResizeObserver(() => {
      const U = bt.current <= ft.current + 0.5;
      ft.current = Rt(), (U || bt.current < ft.current) && $t(ft.current), Ht();
    });
    return _.observe(A), () => _.disconnect();
  }, [B, Rt, $t, Ht]), J.useEffect(() => {
    const A = nt.current;
    if (!A) return;
    const d = (_) => {
      if (!(_.ctrlKey || _.metaKey)) return;
      _.preventDefault();
      const U = A.getBoundingClientRect(), H = _.clientX - U.left, K = (A.scrollLeft + H - dt.current) / bt.current;
      $t(bt.current * Math.exp(-_.deltaY * 25e-4), K, H);
    }, E = () => requestAnimationFrame(Ht);
    return A.addEventListener("wheel", d, { passive: !1 }), A.addEventListener("scroll", E), () => {
      A.removeEventListener("wheel", d), A.removeEventListener("scroll", E);
    };
  }, [$t, Ht]);
  const X = J.useRef(null);
  J.useEffect(() => {
    const A = X.current, d = Yt.current;
    if (!A || !d || B === 0) return;
    const E = d.clientWidth, _ = d.clientHeight, U = window.devicePixelRatio || 1;
    A.width = E * U, A.height = _ * U;
    const H = A.getContext("2d");
    if (!H) return;
    H.setTransform(U, 0, 0, U, 0, 0), H.clearRect(0, 0, E, _);
    const K = E / B, et = 3, G = _ - et * 2;
    R.attempts.forEach((W, Dt) => {
      let dl = _ - et;
      for (const { lane: Ke, size: we } of Wf(W, c.blocks, p)) {
        const Qt = Math.max(0.5, we / Q * G);
        H.fillStyle = Gh[Ke], H.globalAlpha = Y.has(Ke) ? 0.8 : 0.15, H.fillRect(Dt * K, dl - Qt, Math.max(1, K - 0.4), Qt), dl -= Qt;
      }
      H.globalAlpha = 1, W.status === "incomplete" && (H.fillStyle = "#d97706", H.fillRect(Dt * K, 0, Math.max(1.5, K - 0.4), 2.5));
    }), H.strokeStyle = Gh.summary, H.setLineDash([3, 3]), H.lineWidth = 1.5;
    for (const W of rt) {
      const Dt = W * K;
      H.beginPath(), H.moveTo(Dt, 0), H.lineTo(Dt, _), H.stroke();
    }
    H.setLineDash([]), Ht();
  }, [Y, B, rt, Q, p, R, c.blocks, Ht]), J.useEffect(() => {
    const A = Yt.current, d = k.current, E = nt.current;
    if (!A || !d || !E || B === 0) return;
    const _ = (K) => {
      const et = A.getBoundingClientRect(), G = K.clientX - et.left, W = d.getBoundingClientRect(), Dt = K.clientX >= W.left && K.clientX <= W.right, Ke = (E.clientWidth - dt.current) / bt.current >= B - 0.5;
      A.setPointerCapture(K.pointerId), Dt && !Ke ? Lt.current = { mode: "pan", startX: G, startScroll: E.scrollLeft } : Lt.current = { mode: "select", anchorX: G, lastX: G };
    }, U = (K) => {
      const et = Lt.current;
      if (!et) return;
      const G = A.getBoundingClientRect(), W = Math.max(0, Math.min(G.width, K.clientX - G.left));
      if (et.mode === "pan") {
        const Dt = (W - et.startX) / G.width * B;
        E.scrollLeft = et.startScroll + Dt * bt.current;
      } else {
        et.lastX = W;
        const Dt = Math.min(et.anchorX, W), dl = Math.max(et.anchorX, W);
        d.style.left = `${Dt / G.width * 100}%`, d.style.width = `${Math.max(2, dl - Dt) / G.width * 100}%`;
      }
    }, H = () => {
      const K = Lt.current;
      if (Lt.current = null, K?.mode !== "select") {
        Ht();
        return;
      }
      const et = A.getBoundingClientRect();
      if (Math.abs(K.lastX - K.anchorX) < 3) {
        $t(ft.current), E.scrollLeft = 0;
        return;
      }
      const G = Math.max(0, Math.min(K.anchorX, K.lastX) / et.width * B), W = Math.min(B, Math.max(K.anchorX, K.lastX) / et.width * B), Dt = Math.max(2, W - G);
      $t((E.clientWidth - dt.current) / Dt), E.scrollLeft = G * bt.current, Ht();
    };
    return A.addEventListener("pointerdown", _), A.addEventListener("pointermove", U), A.addEventListener("pointerup", H), () => {
      A.removeEventListener("pointerdown", _), A.removeEventListener("pointermove", U), A.removeEventListener("pointerup", H);
    };
  }, [B, $t, Ht]), J.useEffect(() => {
    const A = qt.current;
    if (!(!A || B === 0)) {
      if (M === null) {
        A.style.display = "none";
        return;
      }
      A.style.display = "block", A.style.left = `${(M + 0.5) / B * 100}%`;
    }
  }, [B, M]);
  const P = J.useCallback((A, d = !1) => {
    z(A), d || w({ mode: "attempt" });
    const E = nt.current;
    if (!E) return;
    const _ = bt.current, U = dt.current, H = U + A * _;
    H - E.scrollLeft < U ? E.scrollLeft = A * _ : H + _ - E.scrollLeft > E.clientWidth && (E.scrollLeft = H + _ - E.clientWidth);
  }, []), I = J.useCallback(
    (A) => {
      if (A.key === "Escape") {
        w({ mode: "attempt" });
        return;
      }
      if (A.key !== "ArrowLeft" && A.key !== "ArrowRight" || M === null || B === 0) return;
      const d = M + (A.key === "ArrowRight" ? 1 : -1);
      d < 0 || d >= B || (A.preventDefault(), P(d));
    },
    [B, P, M]
  ), pt = J.useCallback((A) => {
    F((d) => {
      const E = xn;
      if (d.size === E.length) return /* @__PURE__ */ new Set([A]);
      const _ = new Set(d);
      if (_.has(A)) {
        if (_.delete(A), _.size === 0) return new Set(E);
      } else if (_.add(A), _.size === E.length) return new Set(E);
      return _;
    });
  }, []), st = Y.size < xn.length, ee = J.useCallback((A) => st && !Y.has(A), [Y, st]), Se = J.useMemo(() => R.lanes.map((A) => A.lane), [R.lanes]);
  return B === 0 ? /* @__PURE__ */ s.jsxs("div", { className: "space-y-2", "data-residency-empty": !0, children: [
    /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground text-sm", children: y.empty }),
    R.attemptsTruncated ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: y.attemptsTruncated }) : null
  ] }) : /* @__PURE__ */ s.jsxs("div", { className: "space-y-3", "data-residency-board": !0, children: [
    /* @__PURE__ */ s.jsxs("div", { className: "flex flex-wrap items-start justify-between gap-x-6 gap-y-2", children: [
      /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground max-w-3xl text-xs", children: y.coverage }),
      /* @__PURE__ */ s.jsxs("div", { className: "flex shrink-0 items-center gap-2", children: [
        /* @__PURE__ */ s.jsx("div", { className: "flex items-center gap-1 rounded-md border p-0.5", children: ["tokens", "bytes"].map((A) => /* @__PURE__ */ s.jsx(
          rl,
          {
            size: "sm",
            variant: p === A ? "secondary" : "ghost",
            className: "h-6 px-2 text-xs",
            "aria-pressed": p === A,
            onClick: () => q(A),
            children: A
          },
          A
        )) }),
        /* @__PURE__ */ s.jsxs(rl, { size: "sm", variant: "ghost", className: "h-7 px-2 text-xs", onClick: o, disabled: h, children: [
          /* @__PURE__ */ s.jsx(lo, { className: ut("size-3.5", h && "animate-spin") }),
          y.refresh
        ] })
      ] })
    ] }),
    R.attemptsTruncated ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: y.attemptsTruncated }) : null,
    /* @__PURE__ */ s.jsxs("div", { className: "flex flex-wrap items-center gap-1.5", children: [
      Se.map((A) => /* @__PURE__ */ s.jsxs(
        "button",
        {
          type: "button",
          "aria-pressed": !st || Y.has(A),
          onClick: () => pt(A),
          className: ut(
            "focus-visible:ring-ring inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none",
            ee(A) && "opacity-35"
          ),
          children: [
            /* @__PURE__ */ s.jsx("span", { className: ut("size-2 rounded-[3px]", Ze[A]) }),
            Sn(y, A)
          ]
        },
        A
      )),
      /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground/70 ml-auto hidden text-[11px] lg:inline", children: y.hint })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { className: "grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]", children: [
      /* @__PURE__ */ s.jsxs("div", { className: "min-w-0 rounded-md border", tabIndex: 0, onKeyDown: I, "aria-label": y.title, children: [
        /* @__PURE__ */ s.jsxs("div", { ref: Yt, className: "relative h-12 cursor-crosshair touch-none overflow-hidden border-b select-none", children: [
          /* @__PURE__ */ s.jsx("canvas", { ref: X, className: "block h-full w-full" }),
          /* @__PURE__ */ s.jsx("div", { ref: k, className: "border-primary bg-primary/10 absolute inset-y-0 cursor-grab border-x" }),
          /* @__PURE__ */ s.jsx("div", { ref: qt, className: "bg-primary/70 pointer-events-none absolute inset-y-0 w-0.5" }),
          /* @__PURE__ */ s.jsx(
            "div",
            {
              ref: xt,
              className: "text-muted-foreground bg-background/70 pointer-events-none absolute top-1 right-2 rounded px-1 font-mono text-[10px]"
            }
          )
        ] }),
        /* @__PURE__ */ s.jsx("div", { ref: nt, className: "overflow-x-auto", children: /* @__PURE__ */ s.jsxs(
          "div",
          {
            ref: wt,
            className: "group/board relative isolate min-w-max",
            style: { "--residency-colw": "24px" },
            "data-density": "mid",
            children: [
              /* @__PURE__ */ s.jsx("div", { "aria-hidden": !0, className: "pointer-events-none absolute inset-y-0 left-44 -z-10", children: rt.map((A) => /* @__PURE__ */ s.jsx(
                "span",
                {
                  "data-residency-boundary": A,
                  className: "absolute inset-y-0 w-0 border-l-2 border-dashed border-purple-500/50",
                  style: { left: `calc(${A} * var(--residency-colw))` }
                },
                R.attempts[A].attempt_id
              )) }),
              /* @__PURE__ */ s.jsxs("div", { className: "flex border-b", children: [
                /* @__PURE__ */ s.jsx(
                  "div",
                  {
                    "data-residency-label": !0,
                    className: "bg-card text-muted-foreground sticky left-0 z-[5] w-44 shrink-0 border-r px-3 py-1 text-[11px]",
                    children: "attempt →"
                  }
                ),
                R.attempts.map((A, d) => {
                  const E = R.compressionsBefore.get(A.attempt_id) ?? [], _ = () => w({ mode: "compression", compressionId: E[0].compression_id });
                  return /* @__PURE__ */ s.jsxs(
                    "button",
                    {
                      type: "button",
                      "data-attempt-header": !0,
                      "data-lbl": "on",
                      onClick: () => P(d),
                      title: `${Ue(A)}${A.occurred_at ? ` · ${_n(A.occurred_at, r)}` : ""} · ${De(tc(A, p), p)}${A.status === "incomplete" ? ` (${y.lowerBound})` : ""}`,
                      className: ut(
                        "group/hcell relative w-(--residency-colw) shrink-0 overflow-visible py-1 text-center",
                        A.status === "incomplete" && Qh,
                        M === d && "bg-primary/10 shadow-[inset_0_-2px_0_var(--color-primary)]"
                      ),
                      children: [
                        E.length > 0 ? /* @__PURE__ */ s.jsxs(
                          "span",
                          {
                            role: "button",
                            tabIndex: 0,
                            "data-residency-compression-marker": !0,
                            onClick: (U) => {
                              U.stopPropagation(), _();
                            },
                            onKeyDown: (U) => {
                              (U.key === "Enter" || U.key === " ") && (U.stopPropagation(), _());
                            },
                            title: y.compression,
                            className: "bg-card absolute -top-0.5 left-0 z-[5] inline-flex -translate-x-1/2 items-center gap-0.5 rounded-full border border-purple-500/60 px-1 text-[9px] leading-4 text-purple-600",
                            children: [
                              /* @__PURE__ */ s.jsx(Jh, { className: "size-2.5" }),
                              E.length > 1 ? `×${E.length}` : null
                            ]
                          }
                        ) : null,
                        /* @__PURE__ */ s.jsx(
                          "span",
                          {
                            className: ut(
                              "text-foreground text-[11px] font-medium whitespace-nowrap",
                              M === d ? "text-primary" : "group-data-[lbl=off]/hcell:invisible"
                            ),
                            children: Ue(A)
                          }
                        ),
                        A.status === "incomplete" ? /* @__PURE__ */ s.jsx("span", { className: "absolute top-0.5 right-0.5 size-1.5 rounded-full bg-amber-500" }) : null
                      ]
                    },
                    A.attempt_id
                  );
                })
              ] }),
              /* @__PURE__ */ s.jsxs("div", { className: "flex border-b", children: [
                /* @__PURE__ */ s.jsx("div", { className: "bg-card sticky left-0 z-[5] flex w-44 shrink-0 items-end border-r px-3 py-1", children: /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground text-[11px] leading-tight", children: [
                  /* @__PURE__ */ s.jsx("div", { className: "text-foreground/80 font-medium", children: y.composition }),
                  /* @__PURE__ */ s.jsx("div", { children: p })
                ] }) }),
                R.attempts.map((A, d) => {
                  const E = tc(A, p), _ = Wf(A, c.blocks, p), U = R.compressionsBefore.has(A.attempt_id);
                  return /* @__PURE__ */ s.jsx(
                    "button",
                    {
                      type: "button",
                      onClick: () => P(d),
                      title: `${Ue(A)} · ${De(E, p)} ${p}${A.status === "incomplete" ? ` (${y.lowerBound})` : ""}`,
                      className: ut(
                        "flex w-(--residency-colw) shrink-0 items-end justify-center px-px pt-1.5 group-data-[density=full]/board:px-1",
                        U && "border-l-2 border-transparent",
                        A.status === "incomplete" && Qh,
                        M === d && "bg-primary/10"
                      ),
                      style: { height: kf + 8 },
                      children: /* @__PURE__ */ s.jsxs(
                        "span",
                        {
                          className: "flex w-full flex-col justify-end overflow-hidden rounded-t-[2px]",
                          style: { height: Math.max(4, Math.round(E / Q * kf)) },
                          children: [
                            A.status === "incomplete" ? /* @__PURE__ */ s.jsx("span", { className: "h-2 w-full border border-b-0 border-dashed border-amber-500/50 bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]" }) : null,
                            _.map(({ lane: H, size: K }) => /* @__PURE__ */ s.jsx(
                              "span",
                              {
                                className: ut("w-full", Ze[H], ee(H) && "opacity-20"),
                                style: { height: Math.max(2, Math.round(K / Q * kf)) }
                              },
                              H
                            ))
                          ]
                        }
                      )
                    },
                    A.attempt_id
                  );
                })
              ] }),
              R.lanes.map((A) => /* @__PURE__ */ s.jsxs("div", { className: ut(ee(A.lane) && "opacity-35"), children: [
                /* @__PURE__ */ s.jsx("div", { className: "bg-muted/50 border-b", children: /* @__PURE__ */ s.jsxs("div", { className: "bg-muted/50 sticky left-0 z-[5] inline-flex items-center gap-1.5 px-3 py-0.5 text-[10px] font-semibold tracking-wide uppercase", children: [
                  /* @__PURE__ */ s.jsx("span", { className: ut("size-1.5 rounded-[2px]", Ze[A.lane]) }),
                  Sn(y, A.lane),
                  /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground font-normal", children: [
                    "· ",
                    A.rows.length
                  ] })
                ] }) }),
                A.rows.map((d) => /* @__PURE__ */ s.jsx(
                  Gg,
                  {
                    row: d,
                    model: R,
                    measure: p,
                    selectedAttempt: M,
                    onSelectBlock: (E, _) => {
                      _ !== null && P(_, !0), w({ mode: "block", blockId: E });
                    },
                    colwRef: bt,
                    title: ac(y, d)
                  },
                  d.blockId
                ))
              ] }, A.lane))
            ]
          }
        ) })
      ] }),
      /* @__PURE__ */ s.jsx(
        Qg,
        {
          model: R,
          response: c,
          measure: p,
          selectedAttempt: M,
          panel: N,
          locale: r,
          t: y,
          onSelectAttempt: (A) => P(A),
          onSelectBlock: (A) => w({ mode: "block", blockId: A }),
          onSelectCompression: (A) => w({ mode: "compression", compressionId: A })
        }
      )
    ] })
  ] });
}
function Gg({
  row: c,
  model: r,
  measure: y,
  selectedAttempt: o,
  onSelectBlock: h,
  colwRef: D,
  title: R
}) {
  const p = r.attempts.length;
  return /* @__PURE__ */ s.jsxs("div", { className: "border-border/50 flex h-7 items-stretch border-b", "data-residency-row": c.blockId, children: [
    /* @__PURE__ */ s.jsxs(
      "button",
      {
        type: "button",
        onClick: () => h(c.blockId, null),
        className: "bg-card hover:bg-muted/60 sticky left-0 z-[5] flex w-44 shrink-0 items-center gap-1.5 truncate border-r px-3 text-left text-xs",
        title: R,
        children: [
          /* @__PURE__ */ s.jsx("span", { className: ut("size-2 shrink-0 rounded-[3px]", Ze[c.lane]) }),
          /* @__PURE__ */ s.jsx("span", { className: "truncate", children: R }),
          /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground/70 ml-auto shrink-0 font-mono text-[10px]", children: De(za({ estimated_tokens: c.sizeTokens, visible_bytes: c.sizeBytes }, y), y) })
        ]
      }
    ),
    /* @__PURE__ */ s.jsxs("div", { className: "relative grid items-center", style: { gridTemplateColumns: `repeat(${p}, var(--residency-colw))` }, children: [
      o !== null ? /* @__PURE__ */ s.jsx(
        "span",
        {
          className: "bg-primary/8 pointer-events-none absolute inset-y-0",
          style: { left: `calc(${o} * var(--residency-colw))`, width: "var(--residency-colw)" }
        }
      ) : null,
      c.runs.map((q) => /* @__PURE__ */ s.jsx(
        "button",
        {
          type: "button",
          "data-residency-run": !0,
          onClick: (M) => {
            const z = M.currentTarget.getBoundingClientRect(), N = Math.floor((M.clientX - z.left) / Math.max(1, D.current));
            h(c.blockId, Math.min(q.end, q.start + Math.max(0, N)));
          },
          title: R,
          className: ut("mx-px h-2.5 rounded-full", Ze[c.lane], "hover:ring-primary/40 hover:ring-2"),
          style: { gridColumn: `${q.start + 1} / ${q.end + 2}`, gridRow: 1 }
        },
        `run-${q.start}`
      )),
      c.unknownAt.map((q) => /* @__PURE__ */ s.jsx(
        "span",
        {
          "data-residency-unknown": !0,
          title: `${Ue(r.attempts[q])} · ?`,
          className: "border-muted-foreground/50 text-muted-foreground mx-0.5 flex h-2.5 items-center justify-center rounded border border-dashed text-[8px] leading-none group-data-[density=dense]/board:text-[0px]",
          style: { gridColumn: `${q + 1} / ${q + 2}`, gridRow: 1 },
          children: "?"
        },
        `unknown-${q}`
      ))
    ] })
  ] });
}
function Qg({
  model: c,
  response: r,
  measure: y,
  selectedAttempt: o,
  panel: h,
  locale: D,
  t: R,
  onSelectAttempt: p,
  onSelectBlock: q,
  onSelectCompression: M
}) {
  const z = o !== null ? c.attempts[o] ?? null : null;
  return /* @__PURE__ */ s.jsx("div", { className: "min-w-0 space-y-3 rounded-md border p-3 text-sm lg:sticky lg:top-4 lg:max-h-[70vh] lg:self-start lg:overflow-y-auto", "data-residency-panel": h.mode, children: h.mode === "attempt" ? z ? /* @__PURE__ */ s.jsx(
    Vg,
    {
      attempt: z,
      attemptIndex: o,
      response: r,
      model: c,
      measure: y,
      locale: D,
      t: R,
      onSelectBlock: q
    }
  ) : /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground text-xs", children: R.empty }) : h.mode === "block" ? /* @__PURE__ */ s.jsx(
    Zg,
    {
      blockId: h.blockId,
      model: c,
      measure: y,
      t: R,
      onSelectAttempt: p,
      onSelectCompression: M,
      onBack: () => z ? p(o) : void 0
    }
  ) : /* @__PURE__ */ s.jsx(
    Kg,
    {
      compressionId: h.compressionId,
      model: c,
      measure: y,
      locale: D,
      t: R,
      onSelectBlock: q,
      onSelectAttempt: p
    }
  ) });
}
function no({ crumb: c, onCrumb: r, title: y, chips: o }) {
  return /* @__PURE__ */ s.jsxs("div", { className: "space-y-1", children: [
    c && r ? /* @__PURE__ */ s.jsxs("button", { type: "button", onClick: r, className: "text-primary text-xs underline-offset-2 hover:underline", children: [
      "‹ ",
      c
    ] }) : null,
    /* @__PURE__ */ s.jsxs("div", { className: "flex flex-wrap items-center gap-2 font-medium", children: [
      y,
      o
    ] })
  ] });
}
function Vg({
  attempt: c,
  attemptIndex: r,
  response: y,
  model: o,
  measure: h,
  locale: D,
  t: R,
  onSelectBlock: p
}) {
  const [q, M] = J.useState("context"), z = tc(c, h), N = Wf(c, y.blocks, h), w = Ng(N, z, c.context_window_tokens ?? null, h), Y = c.status === "incomplete", F = new Map(o.rows.map((B) => [B.blockId, B]));
  return /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
    /* @__PURE__ */ s.jsx(
      no,
      {
        title: /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          R.snapshot,
          " · ",
          Ue(c)
        ] }),
        chips: /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          c.attempt_no > 1 ? /* @__PURE__ */ s.jsx(ec, { children: R.retryAttempt }) : null,
          /* @__PURE__ */ s.jsx(ec, { className: ut(Y && "border-amber-500/60 text-amber-600"), children: c.status }),
          c.outcome === "failed" ? /* @__PURE__ */ s.jsx(ec, { className: "border-destructive/60 text-destructive", children: c.outcome }) : null
        ] })
      }
    ),
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      /* @__PURE__ */ s.jsx("code", { children: he(c.attempt_id) }),
      c.occurred_at ? ` · ${_n(c.occurred_at, D)}` : null,
      c.model_name ? ` · ${c.model_name}` : null,
      ` · ${c.message_count} msg · ${c.tool_schema_count} schema`
    ] }),
    /* @__PURE__ */ s.jsxs("div", { className: "text-xs", children: [
      R.total,
      ":",
      " ",
      /* @__PURE__ */ s.jsxs("span", { className: "font-mono font-medium", children: [
        De(z, h),
        Y ? `+ (${R.lowerBound})` : "",
        " ",
        h
      ] })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { "data-residency-composition": w.basis, children: [
      /* @__PURE__ */ s.jsxs("div", { className: "mb-1 flex flex-wrap items-baseline justify-between gap-x-2", children: [
        /* @__PURE__ */ s.jsx("div", { className: "text-muted-foreground text-[10px] font-semibold tracking-wide uppercase", children: R.composition }),
        /* @__PURE__ */ s.jsx("div", { className: "text-muted-foreground text-[10px]", children: w.capacity !== null ? R.compositionWindow(`${De(w.capacity, h)} ${h}`) : R.compositionRequest })
      ] }),
      /* @__PURE__ */ s.jsxs("div", { className: ut("bg-muted relative flex h-3 overflow-hidden rounded", w.overflow && "ring-destructive/70 ring-1"), children: [
        w.segments.map(({ lane: B, size: Q, share: rt, width: nt }) => /* @__PURE__ */ s.jsx(
          "span",
          {
            className: Ze[B],
            style: { width: `${nt * 100}%` },
            title: `${Sn(R, B)} · ${De(Q, h)} ${h} · ${aa(rt)}`
          },
          B
        )),
        Y ? /* @__PURE__ */ s.jsx(
          "span",
          {
            className: ut(
              "border border-dashed bg-[repeating-linear-gradient(135deg,transparent_0_3px,var(--color-border)_3px_5px)]",
              w.basis === "window" ? "w-[4%] shrink-0" : "min-w-[6%] flex-1"
            )
          }
        ) : null
      ] }),
      /* @__PURE__ */ s.jsxs("div", { className: "mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px]", children: [
        w.segments.map(({ lane: B, share: Q }) => /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground inline-flex items-center gap-1", children: [
          /* @__PURE__ */ s.jsx("span", { className: ut("size-1.5 rounded-[2px]", Ze[B]) }),
          Sn(R, B),
          " ",
          /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-medium", children: aa(Q) })
        ] }, B)),
        w.freeShare !== null ? /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground inline-flex items-center gap-1", children: [
          /* @__PURE__ */ s.jsx("span", { className: "bg-muted size-1.5 rounded-[2px] border" }),
          R.free,
          " ",
          /* @__PURE__ */ s.jsxs("b", { className: "text-foreground font-medium", children: [
            Y ? "≤ " : "",
            aa(w.freeShare)
          ] })
        ] }) : null
      ] }),
      w.capacity !== null && w.usedShare !== null ? /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground mt-1 text-[11px]", children: [
        R.used,
        ":",
        " ",
        /* @__PURE__ */ s.jsxs("span", { className: "text-foreground font-mono font-medium", children: [
          De(z, h),
          Y ? "+" : "",
          " / ",
          De(w.capacity, h),
          " ",
          h,
          " · ",
          aa(w.usedShare)
        ] }),
        w.overflow ? /* @__PURE__ */ s.jsx("span", { className: "text-destructive ml-2 font-medium", children: R.overflow(aa(w.usedShare - 1)) }) : null
      ] }) : null
    ] }),
    /* @__PURE__ */ s.jsxs("div", { children: [
      /* @__PURE__ */ s.jsxs("div", { className: "mb-1 flex items-center justify-between gap-2", children: [
        /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground text-[10px] font-semibold tracking-wide uppercase", children: [
          R.members,
          " · ",
          /* @__PURE__ */ s.jsx("span", { className: "font-normal tracking-normal normal-case", children: R.membersOfRequest })
        ] }),
        /* @__PURE__ */ s.jsx("div", { className: "flex items-center gap-0.5 rounded-md border p-0.5", children: ["context", "share"].map((B) => /* @__PURE__ */ s.jsx(
          rl,
          {
            size: "sm",
            variant: q === B ? "secondary" : "ghost",
            className: "h-5 px-1.5 text-[10px]",
            "aria-pressed": q === B,
            onClick: () => M(B),
            children: B === "context" ? R.sortContext : R.sortShare
          },
          B
        )) })
      ] }),
      /* @__PURE__ */ s.jsx("ul", { className: "space-y-0.5", "aria-label": R.members, children: Sg(c.members, q, h).map((B) => {
        const Q = F.get(B.block_id), rt = za(B, h);
        return /* @__PURE__ */ s.jsx("li", { children: /* @__PURE__ */ s.jsxs(
          "button",
          {
            type: "button",
            onClick: () => p(B.block_id),
            className: "hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs",
            children: [
              /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground/70 w-5 shrink-0 text-right font-mono text-[10px]", children: B.ordinal }),
              /* @__PURE__ */ s.jsx("span", { className: ut("size-2 shrink-0 rounded-[3px]", Ze[Q?.lane ?? "unknown"]) }),
              /* @__PURE__ */ s.jsxs("span", { className: "min-w-0 flex-1 truncate", children: [
                Q ? ac(R, Q) : he(B.block_id),
                B.resolution_status === "missing" ? /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground italic", children: [
                  " · ",
                  R.memberUnprojected
                ] }) : null
              ] }),
              /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground shrink-0 font-mono tabular-nums", children: De(rt, h) }),
              /* @__PURE__ */ s.jsx("span", { className: "w-12 shrink-0 text-right font-mono font-medium tabular-nums", children: Lg(rt, z) })
            ]
          }
        ) }, `${B.ordinal}`);
      }) })
    ] }),
    Y ? /* @__PURE__ */ s.jsx("p", { className: "border-l-2 border-amber-500/60 pl-2 text-[11px] text-amber-600", children: R.incompleteNote }) : null,
    o.unanchoredCompressions.length > 0 && r === 0 ? /* @__PURE__ */ s.jsxs("p", { className: "text-muted-foreground text-[11px]", children: [
      R.unanchored,
      ": ",
      o.unanchoredCompressions.map((B) => he(B.compression_id)).join(", ")
    ] }) : null
  ] });
}
function Zg({
  blockId: c,
  model: r,
  measure: y,
  t: o,
  onSelectAttempt: h,
  onSelectCompression: D,
  onBack: R
}) {
  const p = r.rows.find((w) => w.blockId === c);
  if (!p) return null;
  const q = r.attempts.length - 1, M = p.removedBy ? r.compressions.find((w) => w.compression_id === p.removedBy) : null, z = p.removedBy === null && p.lastSeen >= 0 && p.lastSeen < q && // Only claim a disappearance when a later COMPLETE inventory omits it.
  p.presence.slice(p.lastSeen + 1).includes("absent"), N = (w, Y) => /* @__PURE__ */ s.jsx("button", { type: "button", className: "text-primary underline-offset-2 hover:underline", onClick: Y, children: w });
  return /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
    /* @__PURE__ */ s.jsx(
      no,
      {
        crumb: o.snapshot,
        onCrumb: R,
        title: /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          /* @__PURE__ */ s.jsx("span", { className: ut("size-2.5 rounded-[3px]", Ze[p.lane]) }),
          /* @__PURE__ */ s.jsx("span", { className: "min-w-0 truncate", children: ac(o, p) })
        ] })
      }
    ),
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      Sn(o, p.lane),
      " · ",
      /* @__PURE__ */ s.jsx("code", { children: he(p.blockId) }),
      p.meta?.content_hash ? /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
        " ",
        "· ",
        /* @__PURE__ */ s.jsx("code", { title: p.meta.content_hash, children: p.meta.content_hash.slice(0, 10) })
      ] }) : null,
      ` · ${De(za({ estimated_tokens: p.sizeTokens, visible_bytes: p.sizeBytes }, y), y)} ${y}`
    ] }),
    /* @__PURE__ */ s.jsxs("div", { children: [
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        o.residence,
        " · ",
        r.attempts.length,
        " attempts"
      ] }),
      /* @__PURE__ */ s.jsx("div", { className: "flex gap-px", children: p.presence.map((w, Y) => /* @__PURE__ */ s.jsx(
        "button",
        {
          type: "button",
          onClick: () => h(Y),
          title: `${Ue(r.attempts[Y])} · ${w}`,
          className: ut(
            "h-2.5 min-w-0.5 flex-1 rounded-[1px]",
            w === "present" && Ze[p.lane],
            w === "absent" && "bg-muted",
            w === "unknown" && "border-muted-foreground/50 border border-dashed bg-transparent"
          )
        },
        Y
      )) }),
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground mt-0.5 flex justify-between text-[10px]", children: [
        /* @__PURE__ */ s.jsx("span", { children: r.attempts[0] ? Ue(r.attempts[0]) : "" }),
        /* @__PURE__ */ s.jsx("span", { children: r.attempts[q] ? Ue(r.attempts[q]) : "" })
      ] })
    ] }),
    /* @__PURE__ */ s.jsxs("dl", { className: "space-y-1.5 text-xs", children: [
      p.firstSeen >= 0 ? /* @__PURE__ */ s.jsxs("div", { children: [
        /* @__PURE__ */ s.jsxs("dt", { className: "text-muted-foreground inline", children: [
          o.firstSeen,
          ": "
        ] }),
        /* @__PURE__ */ s.jsx("dd", { className: "inline", children: N(Ue(r.attempts[p.firstSeen]), () => h(p.firstSeen)) })
      ] }) : null,
      M ? /* @__PURE__ */ s.jsxs("div", { children: [
        /* @__PURE__ */ s.jsxs("dt", { className: "text-muted-foreground inline", children: [
          o.removedBy,
          ": "
        ] }),
        /* @__PURE__ */ s.jsxs("dd", { className: "inline", children: [
          N(he(M.compression_id), () => D(M.compression_id)),
          M.summary_block_id ? /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
            " ",
            /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground", children: [
              "→ ",
              o.continuesIn,
              " "
            ] }),
            N(he(M.summary_block_id), () => D(M.compression_id))
          ] }) : null
        ] })
      ] }) : z ? /* @__PURE__ */ s.jsxs("div", { children: [
        /* @__PURE__ */ s.jsxs("dt", { className: "text-muted-foreground inline", children: [
          o.lastSeen,
          ": "
        ] }),
        /* @__PURE__ */ s.jsxs("dd", { className: "inline", children: [
          N(Ue(r.attempts[p.lastSeen]), () => h(p.lastSeen)),
          " ",
          /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground", children: [
            "· ",
            o.removalUnrecorded
          ] })
        ] })
      ] }) : /* @__PURE__ */ s.jsx("div", { children: /* @__PURE__ */ s.jsx("dd", { className: "text-muted-foreground", children: o.stillPresent }) }),
      p.preservedBy.length > 0 ? /* @__PURE__ */ s.jsxs("div", { children: [
        /* @__PURE__ */ s.jsxs("dt", { className: "text-muted-foreground inline", children: [
          o.preservedBy,
          ": "
        ] }),
        /* @__PURE__ */ s.jsx("dd", { className: "inline", children: p.preservedBy.map((w, Y) => /* @__PURE__ */ s.jsxs("span", { children: [
          Y > 0 ? ", " : null,
          N(he(w), () => D(w))
        ] }, w)) })
      ] }) : null,
      p.summaryOf ? /* @__PURE__ */ s.jsxs("div", { children: [
        /* @__PURE__ */ s.jsxs("dt", { className: "text-muted-foreground inline", children: [
          o.summaryOf,
          ": "
        ] }),
        /* @__PURE__ */ s.jsx("dd", { className: "inline", children: N(he(p.summaryOf), () => D(p.summaryOf)) })
      ] }) : null
    ] })
  ] });
}
function Kg({
  compressionId: c,
  model: r,
  measure: y,
  locale: o,
  t: h,
  onSelectBlock: D,
  onSelectAttempt: R
}) {
  const p = r.compressions.find((z) => z.compression_id === c);
  if (!p) return null;
  const q = p.positioned_before_attempt_id ? r.attempts.findIndex((z) => z.attempt_id === p.positioned_before_attempt_id) : -1, M = (z) => {
    const N = r.rows.find((w) => w.blockId === z);
    return /* @__PURE__ */ s.jsx("li", { children: /* @__PURE__ */ s.jsxs(
      "button",
      {
        type: "button",
        onClick: () => D(z),
        className: "hover:bg-muted/60 flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-xs",
        children: [
          /* @__PURE__ */ s.jsx("span", { className: ut("size-2 shrink-0 rounded-[3px]", Ze[N?.lane ?? "unknown"]) }),
          /* @__PURE__ */ s.jsx("span", { className: "min-w-0 flex-1 truncate", children: N ? ac(h, N) : he(z) }),
          N ? /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground shrink-0 font-mono text-[10px] tabular-nums", children: De(za({ estimated_tokens: N.sizeTokens, visible_bytes: N.sizeBytes }, y), y) }) : null
        ]
      }
    ) }, z);
  };
  return /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
    /* @__PURE__ */ s.jsx(
      no,
      {
        title: /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          /* @__PURE__ */ s.jsx(Jh, { className: "size-3.5 text-purple-600" }),
          h.compression,
          " ",
          he(p.compression_id)
        ] }),
        chips: q < 0 ? /* @__PURE__ */ s.jsx(ec, { className: "border-amber-500/60 text-amber-600", children: p.status }) : null
      }
    ),
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground text-xs", children: [
      p.occurred_at ? _n(p.occurred_at, o) : null,
      q >= 0 ? /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
        " · ",
        h.positionedBefore,
        " ",
        /* @__PURE__ */ s.jsx("button", { type: "button", className: "text-primary underline-offset-2 hover:underline", onClick: () => R(q), children: Ue(r.attempts[q]) })
      ] }) : /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
        " · ",
        h.unanchored
      ] })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { className: "text-xs", children: [
      h.compressionScope,
      ":",
      " ",
      /* @__PURE__ */ s.jsxs("span", { className: "font-mono", children: [
        De(p.before_tokens, "tokens"),
        " → ",
        De(p.after_tokens, "tokens"),
        " tokens"
      ] })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { children: [
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        h.removed,
        " · ",
        p.removed_block_ids.length
      ] }),
      /* @__PURE__ */ s.jsx("ul", { className: "space-y-0.5", children: p.removed_block_ids.map((z) => M(z)) })
    ] }),
    p.preserved_block_ids.length > 0 ? /* @__PURE__ */ s.jsxs("div", { children: [
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: [
        h.preserved,
        " · ",
        p.preserved_block_ids.length
      ] }),
      /* @__PURE__ */ s.jsx("ul", { className: "space-y-0.5", children: p.preserved_block_ids.map((z) => M(z)) })
    ] }) : null,
    /* @__PURE__ */ s.jsxs("div", { children: [
      /* @__PURE__ */ s.jsx("div", { className: "text-muted-foreground mb-1 text-[10px] font-semibold tracking-wide uppercase", children: h.summaryBlock }),
      p.summary_block_id ? /* @__PURE__ */ s.jsx("ul", { children: M(p.summary_block_id) }) : /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground text-xs", children: h.summaryBlockUnknown })
    ] })
  ] });
}
const lc = 50, kg = 15e3, Jg = 200;
function Pi(c, r) {
  return c instanceof to ? `${r} (${c.status}: ${c.message})` : c instanceof Error ? `${r} (${c.message})` : r;
}
function $g(c, r, y) {
  const o = new URL(window.location.href);
  o.searchParams.delete("thread"), c !== "tasks" ? o.searchParams.set("tab", c) : o.searchParams.delete("tab"), r ? o.searchParams.set("task", r) : o.searchParams.delete("task"), y.trim() ? o.searchParams.set("q", y.trim()) : o.searchParams.delete("q"), window.history.replaceState(window.history.state, "", o);
}
function Wh(c) {
  return c.outcome ?? (c.stopped_at ? "unknown" : "running");
}
function Fg({ base: c, locale: r, signal: y, initialTab: o, initialQuery: h, initialTaskId: D, initialStepSeq: R }) {
  const p = J.useMemo(() => Hg(r), [r]), [q, M] = J.useState(D ? o ?? "board" : o === "board" ? "tasks" : o ?? "tasks"), [z, N] = J.useState({ q: h ?? "", kind: "", outcome: "", range: "24h", comp: !1, inc: !1, sort: "started", dir: "desc", page: 1 }), [w, Y] = J.useState("thread"), [F, B] = J.useState({ data: null, loading: !0, error: null }), [Q, rt] = J.useState(0), [nt, wt] = J.useState({ data: null, loading: !0, error: null }), [bt, ft] = J.useState(0), [dt, V] = J.useState(null), [k, qt] = J.useState(D), [xt, Yt] = J.useState({ status: "idle" }), [Lt, Ht] = J.useState(!1), [$t, Rt] = J.useState(null), X = J.useRef(0), P = J.useRef(null), I = J.useCallback((_) => {
    N((U) => ({ ...U, page: 1, ..._ }));
  }, []);
  J.useEffect(() => {
    const _ = ++X.current;
    B((H) => ({ ...H, loading: !0 }));
    const U = window.setTimeout(() => {
      ng(
        c,
        {
          query: z.q,
          kind: z.kind,
          outcome: z.outcome,
          since: Eg(z.range, /* @__PURE__ */ new Date()),
          hasCompactions: z.comp,
          incompleteOnly: z.inc,
          sort: z.sort,
          direction: z.dir,
          limit: lc,
          offset: (z.page - 1) * lc
        },
        y
      ).then((H) => {
        _ === X.current && B({ data: H, loading: !1, error: null });
      }).catch((H) => {
        y.aborted || _ !== X.current || B((K) => ({ ...K, loading: !1, error: Pi(H, p.loadFailed) }));
      });
    }, Jg);
    return () => window.clearTimeout(U);
  }, [c, y, z, Q, p.loadFailed]), J.useEffect(() => {
    let _ = !1;
    const U = () => {
      ug(c, y).then((K) => {
        _ || (wt({ data: K, loading: !1, error: null }), V(/* @__PURE__ */ new Date()));
      }).catch((K) => {
        _ || y.aborted || wt((et) => ({ ...et, loading: !1, error: Pi(K, p.loadFailed) }));
      });
    };
    U();
    const H = q === "health" ? window.setInterval(U, kg) : null;
    return () => {
      _ = !0, H !== null && window.clearInterval(H);
    };
  }, [c, y, q, bt, p.loadFailed]);
  const pt = J.useCallback(
    async (_, U = !1) => {
      U ? Ht(!0) : Yt({ status: "loading" });
      try {
        const H = await qh(c, _, y);
        Yt({ status: "ready", data: H });
      } catch (H) {
        if (y.aborted) return;
        Yt({ status: "error", message: Pi(H, p.loadFailed) });
      } finally {
        Ht(!1);
      }
    },
    [c, y, p.loadFailed]
  );
  J.useEffect(() => {
    k ? pt(k) : Yt({ status: "idle" });
  }, [k, pt]), J.useEffect(() => {
    $g(q, k, z.q);
  }, [q, k, z.q]), J.useEffect(() => {
    const _ = (U) => {
      if (U.key !== "/" || U.isComposing || U.metaKey || U.ctrlKey || U.altKey) return;
      const H = U.composedPath()[0];
      H instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(H.tagName) || (U.preventDefault(), P.current?.focus());
    };
    return document.addEventListener("keydown", _), () => document.removeEventListener("keydown", _);
  }, []);
  const st = J.useCallback((_) => {
    qt(_), M("board");
  }, []), ee = J.useCallback(
    (_) => {
      Rt(null), I({ q: _ });
      const U = F.data?.tasks.find((H) => H.task_id === _.trim());
      U && st(U.task_id);
    },
    [F.data, st, I]
  ), Se = J.useCallback(async () => {
    const _ = z.q.trim();
    if (!_) return;
    const U = F.data?.tasks.find((H) => H.task_id === _);
    if (U) {
      st(U.task_id);
      return;
    }
    if (!/\s/.test(_))
      try {
        const H = await qh(c, _, y);
        Yt({ status: "ready", data: H }), st(_);
      } catch (H) {
        if (y.aborted) return;
        Rt(H instanceof to && H.status === 404 ? p.searchNotFound(_) : Pi(H, p.loadFailed));
      }
  }, [c, z.q, F.data, st, y, p]), A = nt.data ? Og(nt.data.diagnostics) : "ok", d = xt.status === "ready" ? xt.data.projection_status : F.data?.projection_status ?? null, E = xt.status === "ready" ? xt.data.task : F.data?.tasks.find((_) => _.task_id === k) ?? null;
  return /* @__PURE__ */ s.jsxs("div", { className: "space-y-4", "data-residency-app": !0, children: [
    /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground max-w-[68ch] text-sm", children: p.lede }),
    /* @__PURE__ */ s.jsxs("nav", { role: "tablist", className: "flex gap-1 border-b", "aria-label": p.title, children: [
      /* @__PURE__ */ s.jsx($f, { selected: q === "tasks", onClick: () => M("tasks"), label: p.tabTasks, count: F.data ? String(F.data.total) : null, controls: "ctxres-tasks" }),
      /* @__PURE__ */ s.jsx($f, { selected: q === "health", onClick: () => M("health"), label: p.tabHealth, dot: A === "ok" ? null : A, controls: "ctxres-health" }),
      /* @__PURE__ */ s.jsx($f, { selected: q === "board", onClick: () => k && M("board"), label: p.tabBoard, count: k ? he(k, 12) : p.noTaskSelected, disabled: !k, controls: "ctxres-board" })
    ] }),
    q === "tasks" ? /* @__PURE__ */ s.jsxs("section", { id: "ctxres-tasks", role: "tabpanel", className: "space-y-3", "data-residency-tab": "tasks", children: [
      /* @__PURE__ */ s.jsxs("div", { className: "flex flex-wrap items-center gap-2 text-xs", children: [
        /* @__PURE__ */ s.jsxs("label", { className: "bg-background focus-within:ring-ring flex h-8 min-w-0 flex-[1_1_280px] items-center gap-2 rounded-md border px-2 focus-within:ring-1", children: [
          /* @__PURE__ */ s.jsx(bg, { className: "text-muted-foreground size-3.5 shrink-0", "aria-hidden": !0 }),
          /* @__PURE__ */ s.jsx(
            "input",
            {
              ref: P,
              type: "search",
              className: "placeholder:text-muted-foreground min-w-0 flex-1 bg-transparent font-mono text-xs outline-none placeholder:font-sans",
              placeholder: p.searchPlaceholder,
              value: z.q,
              autoComplete: "off",
              spellCheck: !1,
              onChange: (_) => ee(_.target.value),
              onKeyDown: (_) => {
                _.key === "Enter" && (_.preventDefault(), Se());
              },
              "aria-label": p.searchPlaceholder
            }
          ),
          /* @__PURE__ */ s.jsx("kbd", { className: "text-muted-foreground rounded border px-1 font-mono text-[10px]", children: "/" })
        ] }),
        /* @__PURE__ */ s.jsx(Ff, { value: z.kind, onChange: (_) => I({ kind: _ }), options: [["", p.allKinds], ["lead", p.taskKindLead], ["subagent", p.taskKindSubagent]], label: p.colTask }),
        /* @__PURE__ */ s.jsx(
          Ff,
          {
            value: z.outcome,
            onChange: (_) => I({ outcome: _ }),
            options: [["", p.allOutcomes], ["running", p.outcomeRunning], ["completed", p.outcomeCompleted], ["failed", p.outcomeFailed], ["aborted", p.outcomeAborted]],
            label: p.colOutcome
          }
        ),
        /* @__PURE__ */ s.jsx(Ff, { value: z.range, onChange: (_) => I({ range: _ }), options: [["24h", p.range24h], ["7d", p.range7d], ["all", p.rangeAll]], label: p.colStarted }),
        /* @__PURE__ */ s.jsx(Vh, { checked: z.comp, onChange: (_) => I({ comp: _ }), label: p.onlyCompactions }),
        /* @__PURE__ */ s.jsx(Vh, { checked: z.inc, onChange: (_) => I({ inc: _ }), label: p.onlyIncomplete }),
        /* @__PURE__ */ s.jsx("div", { className: "bg-background inline-flex overflow-hidden rounded-md border", role: "group", children: ["thread", "flat"].map((_) => /* @__PURE__ */ s.jsx(
          "button",
          {
            type: "button",
            "aria-pressed": w === _,
            onClick: () => Y(_),
            className: ut("h-7 px-2.5 text-xs", w === _ ? "bg-muted font-semibold" : "text-muted-foreground hover:bg-muted/60"),
            children: _ === "thread" ? p.groupByThread : p.flat
          },
          _
        )) }),
        /* @__PURE__ */ s.jsx(rl, { size: "sm", variant: "ghost", onClick: () => rt((_) => _ + 1), "aria-label": p.refresh, title: p.refresh, children: /* @__PURE__ */ s.jsx(lo, { className: ut("size-3.5", F.loading && "animate-spin"), "aria-hidden": !0 }) })
      ] }),
      $t ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: $t }) : null,
      F.error ? /* @__PURE__ */ s.jsx("p", { className: "text-destructive text-xs", children: F.error }) : null,
      d && !d.running ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: p.recordingOff }) : null,
      F.data ? /* @__PURE__ */ s.jsx(
        Ig,
        {
          response: F.data,
          filters: z,
          group: w,
          loading: F.loading,
          locale: r,
          t: p,
          selectedId: k,
          onSort: (_) => I({ sort: _, dir: z.sort === _ && z.dir === "desc" ? "asc" : "desc" }),
          onSelect: (_) => qt(_),
          onOpen: st,
          onPage: (_) => N((U) => ({ ...U, page: _ })),
          onShowAll: () => I({ range: "all" })
        }
      ) : F.loading ? /* @__PURE__ */ s.jsx(Kf, { className: "h-64 w-full" }) : null
    ] }) : null,
    q === "health" ? /* @__PURE__ */ s.jsxs("section", { id: "ctxres-health", role: "tabpanel", "data-residency-tab": "health", children: [
      nt.error ? /* @__PURE__ */ s.jsx("p", { className: "text-destructive mb-3 text-xs", children: nt.error }) : null,
      nt.data ? /* @__PURE__ */ s.jsx(np, { health: nt.data, refreshedAt: dt, loading: nt.loading, locale: r, t: p, onRefresh: () => ft((_) => _ + 1) }) : nt.loading ? /* @__PURE__ */ s.jsx(Kf, { className: "h-64 w-full" }) : null
    ] }) : null,
    q === "board" && k ? /* @__PURE__ */ s.jsxs("section", { id: "ctxres-board", role: "tabpanel", className: "space-y-3", "data-residency-tab": "board", children: [
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs", children: [
        /* @__PURE__ */ s.jsxs(rl, { size: "sm", variant: "ghost", className: "h-7 px-2", onClick: () => M("tasks"), children: [
          /* @__PURE__ */ s.jsx(kh, { className: "size-3.5", "aria-hidden": !0 }),
          " ",
          p.backToList
        ] }),
        /* @__PURE__ */ s.jsx("code", { className: "text-foreground", title: k, children: k }),
        E ? /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          /* @__PURE__ */ s.jsx("span", { children: E.kind === "lead" ? p.taskKindLead : p.taskKindSubagent }),
          E.agent_name ? /* @__PURE__ */ s.jsx("span", { children: E.agent_name }) : null,
          /* @__PURE__ */ s.jsxs("span", { children: [
            p.colThread,
            " ",
            /* @__PURE__ */ s.jsx("code", { children: E.thread_id })
          ] }),
          /* @__PURE__ */ s.jsx("span", { title: _n(E.started_at, r), children: Su(E.started_at, /* @__PURE__ */ new Date(), p) })
        ] }) : null
      ] }),
      d && !d.running ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: p.recordingOff }) : null,
      d && d.dropped > 0 ? /* @__PURE__ */ s.jsx("p", { className: "text-xs text-amber-600", children: p.dropped(d.dropped) }) : null,
      xt.status === "loading" ? /* @__PURE__ */ s.jsx(Kf, { className: "h-64 w-full" }) : null,
      xt.status === "error" ? /* @__PURE__ */ s.jsx("p", { className: "text-destructive rounded-md border p-3 text-sm", children: xt.message }) : null,
      xt.status === "ready" ? /* @__PURE__ */ s.jsx(Xg, { response: xt.data, locale: r, t: p, refreshing: Lt, onRefresh: () => {
        pt(k, !0);
      }, seedStepSeq: R }, k) : null
    ] }) : null
  ] });
}
function $f({ selected: c, onClick: r, label: y, count: o, dot: h, disabled: D, controls: R }) {
  return /* @__PURE__ */ s.jsxs(
    "button",
    {
      type: "button",
      role: "tab",
      "aria-selected": c,
      "aria-controls": R,
      disabled: D,
      onClick: r,
      className: ut(
        "-mb-px inline-flex items-center gap-2 border-b-2 px-3 pt-2 pb-2.5 text-sm",
        c ? "border-primary text-foreground font-semibold" : "text-muted-foreground border-transparent",
        D ? "cursor-default opacity-55" : "hover:text-foreground"
      ),
      children: [
        h ? /* @__PURE__ */ s.jsx("span", { className: ut("size-2 rounded-full", h === "error" ? "bg-red-500 ring-[3px] ring-red-500/20" : "bg-amber-500 ring-[3px] ring-amber-500/20") }) : null,
        y,
        o ? /* @__PURE__ */ s.jsx("span", { className: "bg-muted text-muted-foreground rounded-full px-1.5 py-px font-mono text-[11px] font-medium", children: o }) : null
      ]
    }
  );
}
function Ff({ value: c, onChange: r, options: y, label: o }) {
  return /* @__PURE__ */ s.jsx("select", { value: c, onChange: (h) => r(h.target.value), "aria-label": o, className: "bg-background h-8 rounded-md border px-2 text-xs", children: y.map(([h, D]) => /* @__PURE__ */ s.jsx("option", { value: h, children: D }, h)) });
}
function Vh({ checked: c, onChange: r, label: y }) {
  return /* @__PURE__ */ s.jsxs("label", { className: "text-muted-foreground inline-flex items-center gap-1.5 whitespace-nowrap", children: [
    /* @__PURE__ */ s.jsx("input", { type: "checkbox", checked: c, onChange: (o) => r(o.target.checked), className: "accent-blue-600" }),
    y
  ] });
}
const Wg = [
  { key: "started", label: (c) => c.colStarted },
  { key: "duration", label: (c) => c.colDuration, align: "right" },
  { key: "attempts", label: (c) => c.colSteps, align: "right" },
  { key: "compactions", label: (c) => c.colCompactions, align: "right" },
  { key: "incomplete", label: (c) => c.colInventory },
  { key: "peak", label: (c) => c.colPeak }
];
function Ig({
  response: c,
  filters: r,
  group: y,
  loading: o,
  locale: h,
  t: D,
  selectedId: R,
  onSort: p,
  onSelect: q,
  onOpen: M,
  onPage: z,
  onShowAll: N
}) {
  const w = /* @__PURE__ */ new Date(), Y = c.tasks, F = new Set(Y.map((V) => V.thread_id)).size, B = Y.filter((V) => Wh(V) === "running").length, Q = Y.reduce((V, k) => V + k.compactions, 0), rt = Y.filter((V) => V.incomplete_attempts > 0).length, nt = Math.max(1, Math.ceil(c.total / lc)), wt = c.total === 0 ? 0 : c.offset + 1, bt = Math.min(c.total, c.offset + Y.length), ft = y === "thread" ? Tg(Y) : [{ threadId: null, rows: Y.map((V) => ({ task: V, depth: 0 })), latestStartedAt: null }], dt = (V, k, qt) => {
    const xt = r.sort === V;
    return /* @__PURE__ */ s.jsx("th", { scope: "col", className: ut("bg-card sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase", qt === "right" && "text-right"), children: /* @__PURE__ */ s.jsxs("button", { type: "button", onClick: () => p(V), className: ut("inline-flex items-center gap-1 hover:underline", xt ? "text-foreground" : "text-muted-foreground"), "aria-sort": xt ? r.dir === "asc" ? "ascending" : "descending" : "none", children: [
      k,
      /* @__PURE__ */ s.jsx("span", { className: "text-[10px]", children: xt ? r.dir === "asc" ? "↑" : "↓" : "↕" })
    ] }) }, V);
  };
  return /* @__PURE__ */ s.jsxs("div", { className: "space-y-2", children: [
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground flex flex-wrap gap-x-4 gap-y-1 text-xs", "data-residency-summary": !0, children: [
      /* @__PURE__ */ s.jsxs("span", { children: [
        /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-semibold", children: Y.length }),
        " ",
        D.onThisPage
      ] }),
      /* @__PURE__ */ s.jsx("span", { children: D.summaryThreads(F) }),
      /* @__PURE__ */ s.jsx("span", { children: D.summaryRunning(B) }),
      /* @__PURE__ */ s.jsx("span", { children: D.summaryCompactions(Q) }),
      /* @__PURE__ */ s.jsx("span", { className: ut(rt > 0 && "text-amber-600"), children: D.summaryIncomplete(rt) })
    ] }),
    /* @__PURE__ */ s.jsx("div", { className: ut("bg-card overflow-x-auto rounded-md border", o && "opacity-60"), children: /* @__PURE__ */ s.jsxs("table", { className: "w-full min-w-[960px] border-collapse text-xs", "data-residency-task-table": !0, children: [
      /* @__PURE__ */ s.jsx("thead", { children: /* @__PURE__ */ s.jsxs("tr", { className: "border-b text-left", children: [
        /* @__PURE__ */ s.jsx("th", { scope: "col", className: "bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase", children: D.colTask }),
        /* @__PURE__ */ s.jsx("th", { scope: "col", className: "bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase", children: D.colThread }),
        Wg.map((V) => dt(V.key, V.label(D), V.align)),
        /* @__PURE__ */ s.jsx("th", { scope: "col", className: "bg-card text-muted-foreground sticky top-0 px-2.5 py-2 text-[11px] font-semibold tracking-wide uppercase", children: D.colOutcome }),
        /* @__PURE__ */ s.jsx("th", { scope: "col", className: "bg-card sticky top-0" })
      ] }) }),
      /* @__PURE__ */ s.jsx("tbody", { children: Y.length === 0 ? /* @__PURE__ */ s.jsx("tr", { children: /* @__PURE__ */ s.jsxs("td", { colSpan: 10, className: "text-muted-foreground px-4 py-8 text-center", children: [
        D.emptyList,
        r.range !== "all" ? /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
          " ",
          /* @__PURE__ */ s.jsx("button", { type: "button", className: "text-blue-600 underline-offset-2 hover:underline", onClick: N, children: D.showAllTime })
        ] }) : null
      ] }) }) : ft.map((V) => /* @__PURE__ */ s.jsx(tp, { section: V, now: w, locale: h, t: D, selectedId: R, onSelect: q, onOpen: M }, V.threadId ?? "flat")) })
    ] }) }),
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground flex flex-wrap items-center justify-between gap-2 px-0.5 text-xs", children: [
      /* @__PURE__ */ s.jsx("span", { children: D.pageInfo(wt, bt, c.total, lc) }),
      /* @__PURE__ */ s.jsxs("div", { className: "flex gap-1", role: "navigation", children: [
        /* @__PURE__ */ s.jsx(rl, { size: "sm", className: "h-6 min-w-6 px-1.5", disabled: r.page <= 1, onClick: () => z(r.page - 1), "aria-label": "‹", children: /* @__PURE__ */ s.jsx(kh, { className: "size-3.5", "aria-hidden": !0 }) }),
        Pg(r.page, nt).map((V) => /* @__PURE__ */ s.jsx(rl, { size: "sm", variant: V === r.page ? "secondary" : "outline", className: "h-6 min-w-6 px-1.5 font-mono", "aria-current": V === r.page ? "page" : void 0, onClick: () => z(V), children: V }, V)),
        /* @__PURE__ */ s.jsx(rl, { size: "sm", className: "h-6 min-w-6 px-1.5", disabled: r.page >= nt, onClick: () => z(r.page + 1), "aria-label": "›", children: /* @__PURE__ */ s.jsx(yg, { className: "size-3.5", "aria-hidden": !0 }) })
      ] })
    ] })
  ] });
}
function Pg(c, r) {
  const y = Math.max(1, Math.min(c - 3, r - 6)), o = Math.min(r, y + 6), h = [];
  for (let D = y; D <= o; D += 1) h.push(D);
  return h;
}
function tp({
  section: c,
  now: r,
  locale: y,
  t: o,
  selectedId: h,
  onSelect: D,
  onOpen: R
}) {
  return /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
    c.threadId ? /* @__PURE__ */ s.jsx("tr", { className: "bg-muted/60 text-muted-foreground border-t", "data-residency-thread-group": c.threadId, children: /* @__PURE__ */ s.jsxs("td", { colSpan: 10, className: "px-2.5 py-1.5", children: [
      o.colThread,
      " ",
      /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-mono font-medium", children: c.threadId }),
      " · ",
      o.tasksInThread(c.rows.length),
      " · ",
      o.latest,
      " ",
      Su(c.latestStartedAt, r, o),
      " ·",
      " ",
      /* @__PURE__ */ s.jsx("a", { className: "text-blue-600 underline-offset-2 hover:underline", href: `/workspace/chats/${encodeURIComponent(c.threadId)}`, children: o.openInChat })
    ] }) }) : null,
    c.rows.map(({ task: p, depth: q }) => /* @__PURE__ */ s.jsx(ap, { task: p, depth: q, now: r, locale: y, t: o, selected: p.task_id === h, onSelect: () => D(p.task_id), onOpen: () => R(p.task_id) }, p.task_id))
  ] });
}
const ep = {
  completed: "bg-emerald-500/10 text-emerald-700",
  running: "bg-blue-500/10 text-blue-600",
  failed: "bg-red-500/10 text-red-600",
  aborted: "bg-amber-500/10 text-amber-600"
};
function lp(c, r) {
  switch (r) {
    case "running":
      return c.outcomeRunning;
    case "completed":
      return c.outcomeCompleted;
    case "failed":
      return c.outcomeFailed;
    case "aborted":
      return c.outcomeAborted;
    default:
      return r;
  }
}
function ap({ task: c, depth: r, now: y, locale: o, t: h, selected: D, onSelect: R, onOpen: p }) {
  const q = Wh(c), M = Math.max(0, c.attempts - c.steps), z = c.attempts - c.incomplete_attempts, N = c.attempts > 0 ? z / c.attempts : 1, w = Mg(c.peak_by_kind), Y = w.reduce((Q, rt) => Q + rt.size, 0), F = c.duration_seconds !== null ? If(c.duration_seconds, h) : h.runningFor(If(Dg(c.started_at, y) ?? 0, h)), B = (Q) => {
    (Q.key === "Enter" || Q.key === " ") && (Q.preventDefault(), p());
  };
  return /* @__PURE__ */ s.jsxs(
    "tr",
    {
      tabIndex: 0,
      "data-residency-task-row": c.task_id,
      "aria-selected": D,
      onClick: R,
      onDoubleClick: p,
      onKeyDown: B,
      className: ut("hover:bg-muted/50 cursor-pointer border-b whitespace-nowrap", D && "bg-primary/10"),
      children: [
        /* @__PURE__ */ s.jsxs("td", { className: ut("px-2.5 py-2", r === 1 && "pl-7"), children: [
          r === 1 ? /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground/70", children: "↳ " }) : null,
          /* @__PURE__ */ s.jsxs("span", { className: "font-mono", title: c.task_id, children: [
            he(c.task_id, 12),
            c.task_id.length > 12 ? "…" : ""
          ] }),
          /* @__PURE__ */ s.jsx("span", { className: ut("ml-1.5 rounded border px-1.5 py-px text-[10px] tracking-wide uppercase", c.kind === "lead" ? "border-blue-500/60 text-blue-600" : "text-muted-foreground"), children: c.kind === "lead" ? "lead" : "sub" }),
          c.agent_name ? /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground ml-1.5", children: c.agent_name }) : null
        ] }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2", children: /* @__PURE__ */ s.jsx("span", { className: "font-mono", title: c.thread_id, children: he(c.thread_id, 14) }) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2 tabular-nums", title: _n(c.started_at, o), children: Su(c.started_at, y, h) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2 text-right tabular-nums", children: F }),
        /* @__PURE__ */ s.jsxs("td", { className: "px-2.5 py-2 text-right tabular-nums", children: [
          c.steps,
          " / ",
          c.attempts,
          M > 0 ? /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground ml-1", title: h.retries(M), children: [
            "↻",
            M
          ] }) : null
        ] }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2 text-right tabular-nums", children: c.compactions > 0 ? /* @__PURE__ */ s.jsxs("span", { className: "font-semibold text-violet-600", children: [
          "✂ ",
          c.compactions
        ] }) : /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground/60", children: "–" }) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2", children: /* @__PURE__ */ s.jsxs("span", { className: ut("inline-flex items-center gap-1.5", c.incomplete_attempts > 0 && "text-amber-600"), children: [
          /* @__PURE__ */ s.jsxs("span", { className: "bg-muted flex h-1.5 w-16 overflow-hidden rounded-full", children: [
            /* @__PURE__ */ s.jsx("i", { className: "block h-full bg-emerald-500", style: { width: `${N * 100}%` } }),
            c.incomplete_attempts > 0 ? /* @__PURE__ */ s.jsx("i", { className: "block h-full bg-[repeating-linear-gradient(135deg,var(--color-amber-500,#f59e0b)_0_3px,transparent_3px_5px)]", style: { width: `${(1 - N) * 100}%` } }) : null
          ] }),
          /* @__PURE__ */ s.jsx("span", { className: "tabular-nums", children: c.incomplete_attempts > 0 ? h.inventoryIncomplete(c.incomplete_attempts) : h.inventoryComplete })
        ] }) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2", children: /* @__PURE__ */ s.jsxs("span", { className: "inline-flex items-center gap-2", children: [
          /* @__PURE__ */ s.jsx("span", { className: "tabular-nums", children: Cg(c.peak_tokens) }),
          Y > 0 ? /* @__PURE__ */ s.jsx("span", { className: "flex h-2 w-16 overflow-hidden rounded-[2px]", title: `${h.peakStackTitle}: ${w.map((Q) => `${Sn(h, Q.lane)} ${aa(Q.size / Y, 0)}`).join(" · ")}`, children: w.map((Q) => /* @__PURE__ */ s.jsx("i", { className: ut("block h-full", Ze[Q.lane]), style: { width: `${Q.size / Y * 100}%` } }, Q.lane)) }) : null,
          c.peak_context_window ? /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground text-[11px] tabular-nums", children: h.peakOfWindow(aa(c.peak_tokens / c.peak_context_window)) }) : null
        ] }) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2", children: /* @__PURE__ */ s.jsxs("span", { className: ut("inline-flex items-center gap-1.5 rounded-full px-2 py-px text-[11px] font-medium", ep[q] ?? "bg-muted text-muted-foreground"), children: [
          /* @__PURE__ */ s.jsx("span", { className: "size-1.5 rounded-full bg-current" }),
          lp(h, q)
        ] }) }),
        /* @__PURE__ */ s.jsx("td", { className: "px-2.5 py-2 text-right", children: /* @__PURE__ */ s.jsx(
          rl,
          {
            size: "sm",
            className: "h-6 px-2 text-[11px]",
            onClick: (Q) => {
              Q.stopPropagation(), p();
            },
            children: h.openBoard
          }
        ) })
      ]
    }
  );
}
function np({ health: c, refreshedAt: r, loading: y, locale: o, t: h, onRefresh: D }) {
  const R = /* @__PURE__ */ new Date(), p = c.status, q = c.storage, M = c.quality, z = c.config, N = p.running ? "running" : p.enabled ? "stopped" : "disabled", w = J.useMemo(() => zg(c.throughput, /* @__PURE__ */ new Date()), [c.throughput]), Y = w.reduce((ft, dt) => dt.events > ft.events ? dt : ft, w[0] ?? { minute: "", events: 0 }), F = w[w.length - 1]?.events ?? 0, B = q?.rows ?? {}, Q = q?.table_prefix ?? p.table_prefix ?? "ctxres_", rt = B[`${Q}tasks`] ?? 0, nt = B[`${Q}attempts`] ?? 0, wt = B[`${Q}members`] ?? 0, bt = B[`${Q}compactions`] ?? 0;
  return /* @__PURE__ */ s.jsxs("div", { className: "space-y-3", "data-residency-health": N, children: [
    /* @__PURE__ */ s.jsxs("div", { className: "bg-card flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md border px-3.5 py-3 text-xs", children: [
      /* @__PURE__ */ s.jsxs("span", { className: "inline-flex items-center gap-2 text-sm font-semibold", children: [
        /* @__PURE__ */ s.jsx("span", { className: ut("size-2.5 rounded-full ring-4", N === "running" ? "bg-emerald-500 ring-emerald-500/15" : N === "stopped" ? "bg-red-500 ring-red-500/15" : "bg-muted-foreground ring-muted-foreground/15") }),
        N === "running" ? h.recording : N === "stopped" ? h.notRecording : h.recordingDisabled
      ] }),
      /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground flex flex-wrap gap-x-3.5 gap-y-1", children: [
        /* @__PURE__ */ s.jsxs("span", { children: [
          h.database,
          " ",
          /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-medium", children: q?.backend ?? "—" })
        ] }),
        /* @__PURE__ */ s.jsxs("span", { children: [
          h.tablePrefix,
          " ",
          /* @__PURE__ */ s.jsx("code", { children: Q })
        ] }),
        /* @__PURE__ */ s.jsxs("span", { children: [
          h.lastWrite,
          " ",
          /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-medium tabular-nums", children: Su(p.last_flush_at, R, h) })
        ] }),
        /* @__PURE__ */ s.jsxs("span", { children: [
          h.lastEvent,
          " ",
          /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-medium tabular-nums", children: Su(p.last_event_at, R, h) })
        ] }),
        /* @__PURE__ */ s.jsxs("span", { children: [
          h.uptime,
          " ",
          /* @__PURE__ */ s.jsx("b", { className: "text-foreground font-medium tabular-nums", children: p.uptime_seconds != null ? If(p.uptime_seconds, h) : "—" })
        ] })
      ] }),
      /* @__PURE__ */ s.jsx("span", { className: "flex-1" }),
      /* @__PURE__ */ s.jsxs(rl, { size: "sm", className: "h-7", onClick: D, children: [
        /* @__PURE__ */ s.jsx(lo, { className: ut("size-3.5", y && "animate-spin"), "aria-hidden": !0 }),
        r ? h.refreshedAt(Zf(r.toISOString(), o)) : h.refresh
      ] })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { className: "grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-2.5", children: [
      /* @__PURE__ */ s.jsx(bn, { label: h.queueDepth, value: /* @__PURE__ */ s.jsxs(s.Fragment, { children: [
        p.queue_depth,
        " ",
        /* @__PURE__ */ s.jsxs("span", { className: "text-muted-foreground text-xs font-normal", children: [
          "/ ",
          p.queue_capacity ?? "?"
        ] })
      ] }), sub: h.flushEvery(p.flush_interval_ms ?? z.flush_interval_ms) }),
      /* @__PURE__ */ s.jsx(bn, { label: h.accepted, value: p.accepted, sub: h.sinceStart }),
      /* @__PURE__ */ s.jsx(bn, { label: h.written, value: p.flushed, sub: p.last_batch_events ? h.lastBatch(p.last_batch_events, p.last_batch_ms ?? 0) : h.noBatchYet }),
      /* @__PURE__ */ s.jsx(bn, { label: h.droppedTile, value: p.dropped, warn: p.dropped > 0, sub: p.dropped > 0 ? h.lastDropAt(Zf(p.last_drop_at ?? null, o)) : h.noDrops }),
      /* @__PURE__ */ s.jsx(bn, { label: h.writeFailures, value: p.write_failures, warn: p.write_failures > 0, sub: h.writeFailuresSub }),
      /* @__PURE__ */ s.jsx(bn, { label: h.estimator, value: /* @__PURE__ */ s.jsx("code", { className: "text-[13px] break-all", children: p.estimator }), sub: h.readCap(p.max_attempts) })
    ] }),
    /* @__PURE__ */ s.jsxs("div", { className: "grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-3", children: [
      /* @__PURE__ */ s.jsxs(bu, { title: h.throughput, sub: h.throughputSub, children: [
        /* @__PURE__ */ s.jsx(up, { series: w, label: h.throughputSub }),
        /* @__PURE__ */ s.jsxs("dl", { className: "mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-xs", children: [
          /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: h.peakPerMinute }),
          /* @__PURE__ */ s.jsxs("dd", { className: "tabular-nums", children: [
            h.perMinute(Y.events),
            Y.events > 0 ? ` (${Zf(Y.minute.replace("Z", ":00Z"), o)})` : ""
          ] }),
          /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: h.currentPerMinute }),
          /* @__PURE__ */ s.jsx("dd", { className: "tabular-nums", children: h.perMinute(F) })
        ] })
      ] }),
      /* @__PURE__ */ s.jsx(bu, { title: h.storage, sub: h.storageSub, children: q ? /* @__PURE__ */ s.jsxs("dl", { className: "grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 text-xs", children: [
        /* @__PURE__ */ s.jsx("dt", { children: /* @__PURE__ */ s.jsxs("code", { children: [
          Q,
          "tasks"
        ] }) }),
        /* @__PURE__ */ s.jsxs("dd", { className: "tabular-nums", children: [
          h.rows(rt),
          " · ",
          h.openTasks(M?.tasks_open ?? 0)
        ] }),
        /* @__PURE__ */ s.jsx("dt", { children: /* @__PURE__ */ s.jsxs("code", { children: [
          Q,
          "attempts"
        ] }) }),
        /* @__PURE__ */ s.jsxs("dd", { className: "tabular-nums", children: [
          h.rows(nt),
          " · ",
          h.avgPerTask(rt > 0 ? (nt / rt).toFixed(1) : "0")
        ] }),
        /* @__PURE__ */ s.jsx("dt", { children: /* @__PURE__ */ s.jsxs("code", { children: [
          Q,
          "members"
        ] }) }),
        /* @__PURE__ */ s.jsxs("dd", { className: "tabular-nums", children: [
          h.rows(wt),
          " · ",
          h.avgPerAttempt(nt > 0 ? (wt / nt).toFixed(1) : "0")
        ] }),
        /* @__PURE__ */ s.jsx("dt", { children: /* @__PURE__ */ s.jsxs("code", { children: [
          Q,
          "compactions"
        ] }) }),
        /* @__PURE__ */ s.jsx("dd", { className: "tabular-nums", children: h.rows(bt) }),
        /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: h.databaseFile }),
        /* @__PURE__ */ s.jsxs("dd", { className: "font-mono break-all", children: [
          q.database ?? q.backend,
          q.file_bytes != null ? ` · ${Rg(q.file_bytes)}` : ""
        ] }),
        /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: h.earliestRecord }),
        /* @__PURE__ */ s.jsx("dd", { className: "tabular-nums", children: _n(q.earliest_task_started_at, o) }),
        /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: h.retention }),
        /* @__PURE__ */ s.jsx("dd", { children: h.retentionNone })
      ] }) : /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground text-xs", children: h.noStorage }) }),
      /* @__PURE__ */ s.jsx(bu, { title: h.quality, sub: h.qualitySub, children: M ? /* @__PURE__ */ s.jsxs("div", { className: "space-y-2.5", children: [
        /* @__PURE__ */ s.jsx(xu, { label: h.qComplete, value: `${M.attempts_complete} / ${M.attempts_total}${M.attempts_total > 0 ? ` · ${aa(M.attempts_complete / M.attempts_total)}` : ""}`, fraction: M.attempts_total > 0 ? M.attempts_complete / M.attempts_total : 1 }),
        /* @__PURE__ */ s.jsx(xu, { label: h.qIncomplete, value: String(M.attempts_incomplete), fraction: M.attempts_total > 0 ? M.attempts_incomplete / M.attempts_total : 0, warn: M.attempts_incomplete > 0 }),
        /* @__PURE__ */ s.jsx(xu, { label: h.qPositioned, value: `${M.compactions_positioned} / ${M.compactions_total}`, fraction: M.compactions_total > 0 ? M.compactions_positioned / M.compactions_total : 1 }),
        /* @__PURE__ */ s.jsx(xu, { label: h.qUnanchored, value: String(M.compactions_unanchored), fraction: M.compactions_total > 0 ? M.compactions_unanchored / M.compactions_total : 0, warn: M.compactions_unanchored > 0 }),
        /* @__PURE__ */ s.jsx(xu, { label: h.qStale(M.stale_after_minutes), value: String(M.tasks_stale), fraction: rt > 0 ? M.tasks_stale / rt : 0, warn: M.tasks_stale > 0 })
      ] }) : /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground text-xs", children: h.noStorage }) }),
      /* @__PURE__ */ s.jsx(bu, { title: h.diagnostics, sub: h.items(c.diagnostics.length), children: /* @__PURE__ */ s.jsx("ul", { className: "space-y-2", "data-residency-diagnostics": !0, children: c.diagnostics.map((ft) => {
        const dt = h.diagnosticCopy(ft, c);
        return /* @__PURE__ */ s.jsxs(
          "li",
          {
            "data-level": ft.level,
            className: ut("grid grid-cols-[8px_1fr] gap-2.5 rounded-md border px-3 py-2.5", ft.level === "warning" && "border-amber-500/60 bg-amber-500/10", ft.level === "error" && "border-red-500/60 bg-red-500/10"),
            children: [
              /* @__PURE__ */ s.jsx("i", { className: ut("mt-1.5 size-2 rounded-full", ft.level === "ok" ? "bg-emerald-500" : ft.level === "warning" ? "bg-amber-500" : "bg-red-500") }),
              /* @__PURE__ */ s.jsxs("div", { className: "min-w-0", children: [
                /* @__PURE__ */ s.jsx("b", { className: "block text-sm font-semibold", children: dt.title }),
                /* @__PURE__ */ s.jsx("p", { className: "text-muted-foreground mt-0.5 text-xs", children: dt.detail }),
                dt.remedy ? /* @__PURE__ */ s.jsxs("p", { className: "mt-1 text-xs", children: [
                  h.remedy,
                  ": ",
                  dt.remedy
                ] }) : null,
                ft.affected.length > 0 ? /* @__PURE__ */ s.jsxs("p", { className: "mt-1 font-mono text-xs break-all", children: [
                  h.affectedTasks,
                  ": ",
                  ft.affected.map((V) => he(V, 12)).join(", ")
                ] }) : null
              ] })
            ]
          },
          ft.code
        );
      }) }) })
    ] }),
    /* @__PURE__ */ s.jsx(bu, { title: h.configEcho, sub: h.configEchoSub, children: /* @__PURE__ */ s.jsxs("dl", { className: "grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 font-mono text-xs", children: [
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "enabled" }),
      /* @__PURE__ */ s.jsx("dd", { children: String(z.enabled) }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "max_attempts" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.max_attempts }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "queue_capacity" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.queue_capacity }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "flush_interval_ms" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.flush_interval_ms }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "stale_task_after_minutes" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.stale_task_after_minutes }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "context_windows" }),
      /* @__PURE__ */ s.jsx("dd", { className: "break-all", children: Object.keys(z.context_windows).length > 0 ? JSON.stringify(z.context_windows) : h.notConfigured }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "default_context_window" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.default_context_window ?? h.notConfigured }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground", children: "table_prefix" }),
      /* @__PURE__ */ s.jsx("dd", { children: z.table_prefix }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground font-sans", children: h.extensionVersion }),
      /* @__PURE__ */ s.jsx("dd", { children: z.extension_version ? `deerflow-extension-context-residency ${z.extension_version}` : h.unknownVersion }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground font-sans", children: h.apiVersion }),
      /* @__PURE__ */ s.jsx("dd", { children: z.api_version ?? "—" }),
      /* @__PURE__ */ s.jsx("dt", { className: "text-muted-foreground font-sans", children: h.placements }),
      /* @__PURE__ */ s.jsx("dd", { children: [...z.placements, z.scopes.join(" + ")].join(" · ") })
    ] }) })
  ] });
}
function bn({ label: c, value: r, sub: y, warn: o }) {
  return /* @__PURE__ */ s.jsxs("div", { className: ut("bg-card min-w-0 rounded-md border px-3.5 py-3", o && "border-amber-500"), children: [
    /* @__PURE__ */ s.jsxs("div", { className: "text-muted-foreground flex justify-between gap-1.5 text-[11px] font-semibold tracking-wide uppercase", children: [
      c,
      o ? /* @__PURE__ */ s.jsx("span", { "aria-hidden": !0, children: "⚠" }) : null
    ] }),
    /* @__PURE__ */ s.jsx("div", { className: ut("mt-1 text-2xl font-semibold tabular-nums", o && "text-amber-600"), children: r }),
    /* @__PURE__ */ s.jsx("div", { className: "text-muted-foreground mt-0.5 text-xs", children: y })
  ] });
}
function bu({ title: c, sub: r, children: y }) {
  return /* @__PURE__ */ s.jsxs("section", { className: "bg-card min-w-0 rounded-md border p-3.5", children: [
    /* @__PURE__ */ s.jsxs("h2", { className: "text-muted-foreground mb-2.5 flex flex-wrap items-baseline justify-between gap-2 text-[11px] font-semibold tracking-wide uppercase", children: [
      c,
      /* @__PURE__ */ s.jsx("span", { className: "font-normal tracking-normal normal-case", children: r })
    ] }),
    y
  ] });
}
function xu({ label: c, value: r, fraction: y, warn: o }) {
  return /* @__PURE__ */ s.jsxs("div", { className: "grid grid-cols-[1fr_max-content] items-center gap-x-2.5 gap-y-1 text-xs", children: [
    /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground", children: c }),
    /* @__PURE__ */ s.jsx("span", { className: ut("font-semibold tabular-nums", o && "text-amber-600"), children: r }),
    /* @__PURE__ */ s.jsx("span", { className: "bg-muted col-span-2 h-1.5 overflow-hidden rounded-full", children: /* @__PURE__ */ s.jsx("i", { className: ut("block h-full", o ? "bg-amber-500" : "bg-emerald-500"), style: { width: `${Math.min(100, Math.max(0, y * 100))}%` } }) })
  ] });
}
function up({ series: c, label: r }) {
  const D = c.map((z) => z.events), { line: R, area: p, max: q } = Ag(D, 600, 88, 4), M = (z) => 84 - z / q * 80;
  return /* @__PURE__ */ s.jsxs("div", { className: "relative", children: [
    /* @__PURE__ */ s.jsxs("svg", { viewBox: "0 0 600 88", preserveAspectRatio: "none", className: "block h-22 w-full", role: "img", "aria-label": r, children: [
      [0, q / 2, q].map((z) => /* @__PURE__ */ s.jsx("line", { x1: 4, x2: 596, y1: M(z), y2: M(z), className: "stroke-border", strokeWidth: 1, vectorEffect: "non-scaling-stroke" }, z)),
      /* @__PURE__ */ s.jsx("path", { d: p, className: "fill-indigo-500/15" }),
      /* @__PURE__ */ s.jsx("path", { d: R, className: "fill-none stroke-indigo-500", strokeWidth: 1.6, strokeLinejoin: "round", vectorEffect: "non-scaling-stroke" })
    ] }),
    /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground absolute top-0 right-1 font-mono text-[10px]", children: q }),
    /* @__PURE__ */ s.jsx("span", { className: "text-muted-foreground absolute right-1 bottom-0 font-mono text-[10px]", children: "0" })
  ] });
}
const ip = "community.context-residency", Zh = "board";
function cp() {
  const c = new URLSearchParams(window.location.search), r = c.get("step"), y = r !== null && /^\d+$/.test(r) ? Number(r) : null, o = c.get("tab");
  return {
    tab: o === "tasks" || o === "health" || o === "board" ? o : null,
    // The conversation-menu action arrives as `?thread=`; it becomes the index query.
    query: c.get("q") ?? c.get("thread"),
    taskId: c.get("task"),
    stepSeq: y
  };
}
function sp() {
  const c = ["styles", "css"].join(".");
  return new URL(c, import.meta.url).href;
}
function fp(c, r) {
  const y = document.createElement("link");
  y.rel = "stylesheet", y.crossOrigin = "use-credentials", y.href = sp();
  const o = document.createElement("div");
  c.append(y, o);
  const h = cp(), D = eg.createRoot(o);
  return D.render(
    J.createElement(Fg, {
      base: lg(import.meta.url),
      locale: r.locale,
      signal: r.signal,
      initialTab: h.tab,
      initialQuery: h.query ?? r.threadId ?? null,
      initialTaskId: h.taskId,
      initialStepSeq: h.stepSeq
    })
  ), {
    dispose() {
      D.unmount(), y.remove(), o.remove();
    }
  };
}
const op = {
  apiVersion: 1,
  module: "context-residency.v1",
  icon: "layers",
  surfaces: [
    {
      id: Zh,
      slot: "page",
      title: "Context residency",
      navigation: { label: "Context residency", labelZh: "上下文留存", icon: "layers" },
      mount: fp
    }
  ],
  conversationActions(c, r = "en") {
    const y = r.startsWith("zh");
    return {
      label: y ? "上下文留存" : "Context residency",
      icon: "layers",
      actions: [
        {
          id: "open-residency",
          label: y ? "查看这个会话的上下文留存" : "Open context residency for this conversation",
          icon: "layers",
          available: (o) => o.enabled === !0,
          async execute(o) {
            const h = new URL(`/workspace/extensions/${encodeURIComponent(ip)}/${Zh}`, window.location.origin);
            h.searchParams.set("thread", o.thread.thread_id), window.location.assign(h.toString());
          }
        }
      ]
    };
  }
};
export {
  op as default
};
